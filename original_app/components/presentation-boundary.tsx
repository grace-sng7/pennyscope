'use client';
import { Component, type ReactNode } from 'react';
import { plainFromResponse } from '../lib/plain-chat';
import { VerificationWarning } from './verification-warning';

export function PlainResult({ response }: { response: unknown }) {
  const reply = plainFromResponse(response);
  return <p style={{ whiteSpace: 'pre-wrap' }}>{reply?.text ?? 'The answer could not be displayed in a card. Your confirmed information is kept.'}<VerificationWarning verification={reply?.verification} /></p>;
}

export class PresentationBoundary extends Component<{ children: ReactNode; fallback: ReactNode; resetKey?: unknown }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidUpdate(previous: Readonly<{ children: ReactNode; fallback: ReactNode; resetKey?: unknown }>) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}
