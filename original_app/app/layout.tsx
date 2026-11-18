import type { Metadata } from 'next';
import './globals.css';
import './assumptions.css';
export const metadata:Metadata={title:'Pennyscope',description:'See every assumption. Explore your next move.'};
// Sketchbook type: Nunito (UI), Instrument Sans (answers and typing), Kalam (numbers), Caveat (handwritten labels).
const FONTS = 'https://fonts.googleapis.com/css2?family=Caveat:wght@500;600;700&family=Instrument+Sans:wght@400;500;600;700&family=Kalam:wght@400;700&family=Nunito:wght@400;500;600;700;800;900&display=swap';
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>) {return <html lang="en"><head><link rel="preconnect" href="https://fonts.googleapis.com" /><link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" /><link rel="stylesheet" href={FONTS} /></head><body>{children}</body></html>;}
