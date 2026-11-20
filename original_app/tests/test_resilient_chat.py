"""Item evidence, combined charges and bounded recovery through the API."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import extraction_service as e
import orchestration as o
import chat_fallback
import factor_selection as fs
import extraction_evidence as evidence
from factor_registry import get_registry
from legacy_main import app

ORIGINAL='Nina, Leo, and I shared a $30 pizza equally. Nina also had a $10 salad, and Leo had a $10 drink. Tax and tip together were $10. We agreed to split that $10 in proportion to what each of us ordered before tax and tip. How much does each person owe?'
PARAPHRASE="The $30 pizza was shared equally by Nina, Leo, and me. The $10 salad was Nina’s. The $10 drink was Leo’s. Tax and tip together cost $10, allocated in proportion to each person’s pre-tax order. What does each person owe?"
ITEMS=[dict(name='pizza',amount=30,shared_by=['Nina','Leo','me']),dict(name='salad',amount=10,shared_by=['Nina']),dict(name='drink',amount=10,shared_by=['Leo'])]
SHARES={'Nina':24,'Leo':24,'me':12}


def extraction(question):
    facts=dict(participants=['Nina','Leo','me'],split_method='itemized',items=ITEMS,tax_and_tip_amount=10)
    return dict(target_variable='amounts_owed',factors=[dict(variable=k,value=json.dumps(v) if isinstance(v,(list,dict)) else v,unit='text' if isinstance(v,(list,str,dict)) else '$',role='known',source='stated',source_detail='Supplied',evidence=dict(source='question',quote=question)) for k,v in facts.items()],goal_summary='Allocate the meal and combined charge.',confidence_note='Literal items and ownership.')


def main_draft():
    return dict(model='bill_split',target_variable='amounts_owed',inputs=dict(method='itemized',people=['Nina','Leo','me'],items=ITEMS,tax_and_tip=10),bindings=dict(method='split_method',people='participants',items='items',tax_and_tip='tax_and_tip_amount'),
                factors=[dict(variable='amounts_owed',value=json.dumps(SHARES),unit='$',role='derived',source='inferred',source_detail='Main calculation')],results={'amounts_owed':SHARES},headline='Nina owes $24, Leo owes $24, and you owe $12.',calculation='Pretax shares are 20, 20, 10; the combined 10 is allocated 4, 4, 2.',assumptions=[])


class ResilientChat(unittest.TestCase):
    def setUp(self):e.PENDING_ROUTES.clear();o.CACHE.clear();o.PENDING_REVIEWS.clear()

    def test_original_and_possessive_paraphrase_calculate_without_question(self):
        for question in (ORIGINAL,PARAPHRASE):
            o.CACHE.clear()
            raw=extraction(question)
            if question==ORIGINAL:
                next(f for f in raw['factors'] if f['variable']=='split_method')['value']='custom'
            with TestClient(app) as client,patch('gemini_gateway.call_json',side_effect=[{'model':'bill_split'},raw]):
                r=client.post('/extract',json=dict(user_message=question,reference_date='2026-11-16',timezone='America/New_York'))
            self.assertEqual(r.status_code,200);ex=r.json();self.assertNotIn('chat_fallback',ex)
            with TestClient(app) as client,patch.object(o,'call_json',side_effect=[main_draft(),{'decision':'approved'}]):
                r=client.post('/calculate',json=dict(original_question=question,assumptions=ex['assumptions'],extraction_meta={k:v for k,v in ex.items() if k not in ('assumptions','clarification_questions')}))
            self.assertEqual(r.status_code,200);result=r.json()
            self.assertEqual(result['missing_inputs'],[])
            self.assertEqual(json.loads(next(f['value'] for f in result['factors'] if f['variable']=='amounts_owed')),SHARES)
            self.assertEqual(result['verification']['status'],'matched')

    def test_unsupported_owner_price_and_duplicate_items_remain_rejected(self):
        for mutate in (lambda items:items[1].update(shared_by=['Leo']),lambda items:items[1].update(amount=12),lambda items:items[0].update(shared_by=['Nina','Leo']),lambda items:items.append(copy.deepcopy(items[1]))):
            items=copy.deepcopy(ITEMS);mutate(items)
            raw=extraction(ORIGINAL);next(f for f in raw['factors'] if f['variable']=='items')['value']=json.dumps(items)
            with patch('gemini_gateway.call_json',side_effect=[copy.deepcopy(raw),copy.deepcopy(raw)]),self.assertRaises(HTTPException):
                fs.select(get_registry('bill_split'),ORIGINAL,reference_date='2026-11-16',timezone='America/New_York')

    def test_possessive_can_link_to_previously_priced_item(self):
        text='The salad cost $10. The salad was Nina’s.'
        self.assertTrue(evidence._item_claims([dict(name='salad',amount=10,shared_by=['Nina'])],text,['nina','leo','me']))
        self.assertFalse(evidence._item_claims([dict(name='salad',amount=10,shared_by=['Leo'])],text,['nina','leo','me']))

    def test_forced_extraction_failure_gets_one_plain_response_and_keeps_confirmed_facts(self):
        error=HTTPException(502,'Forced structural failure')
        error.confirmed_factors=[dict(variable='participants',value='["Nina","Leo","me"]',unit='text',source='stated',source_detail='User names')]
        with TestClient(app) as client,patch.object(e,'extract',side_effect=error),patch('gemini_gateway.call_text',return_value='ANSWER: Nina owes $24, Leo owes $24, and you owe $12.') as plain:
            r=client.post('/extract',json=dict(user_message=ORIGINAL,reference_date='2026-11-16',timezone='America/New_York'))
        self.assertEqual(r.status_code,200);result=r.json()
        self.assertEqual(result['chat_fallback']['kind'],'answer');self.assertIn('$24',result['chat_fallback']['text'])
        self.assertEqual(result['chat_fallback']['verification']['status'],'unverified')
        self.assertEqual(result['assumptions'][0]['variable'],'participants');self.assertEqual(result['clarification_questions'],[])
        plain.assert_called_once();payload=json.loads(plain.call_args.args[1])
        self.assertEqual(payload['original_question'],ORIGINAL);self.assertEqual(len(payload['confirmed_facts']),1)

    def test_existing_main_survives_bad_card_metadata_without_another_llm(self):
        raw=dict(status='conditional',answer={'headline':'Nina $24, Leo $24, you $12.'},factors=[{'bad':'card metadata'}])
        with TestClient(app) as client,patch.object(o,'calculate',return_value=raw),patch('gemini_gateway.call_text') as plain:
            r=client.post('/calculate',json=dict(original_question=ORIGINAL,assumptions=[]))
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['chat_fallback']['text'],raw['answer']['headline'])
        plain.assert_not_called()

    def test_failed_plain_attempt_states_known_information_without_bogus_question(self):
        fact=dict(variable='current_savings',value=350,unit='$',source='stated',source_detail='User')
        with patch('gemini_gateway.call_text',side_effect=HTTPException(502,'Provider down')) as plain:
            result=chat_fallback.respond('How much will I save?',[fact])
        plain.assert_called_once();self.assertEqual(result['kind'],'limitation')
        self.assertIn('350',result['text']);self.assertIn('could not determine',result['text']);self.assertNotIn('?',result['text'])

    def test_real_missing_information_is_one_plain_question_without_icon(self):
        with patch('gemini_gateway.call_text',return_value='QUESTION: What is the price of the salad?'):
            result=chat_fallback.respond('Nina had a salad. What does she owe?')
        self.assertEqual(result,{'kind':'question','text':'What is the price of the salad?'})

if __name__=='__main__':unittest.main()
