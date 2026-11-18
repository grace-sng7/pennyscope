import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
import './assumptions.css';
export const metadata:Metadata={title:'Pennyscope',description:'See every assumption. Explore your next move.'};

// Sketchbook type, self-hosted (SIL OFL, see app/fonts/OFL-LICENSES.txt): Nunito for the UI,
// Instrument Sans for answers and typing, Kalam for numbers, Caveat for handwritten labels.
const nunito = localFont({ src: './fonts/nunito-latin-wght-normal.woff2', weight: '200 1000', variable: '--font-nunito', display: 'swap' });
const instrument = localFont({ src: './fonts/instrument-sans-latin-wght-normal.woff2', weight: '400 700', variable: '--font-instrument', display: 'swap' });
const caveat = localFont({ src: './fonts/caveat-latin-wght-normal.woff2', weight: '400 700', variable: '--font-caveat', display: 'swap' });
const kalam = localFont({ src: [{ path: './fonts/kalam-latin-400-normal.woff2', weight: '400' }, { path: './fonts/kalam-latin-700-normal.woff2', weight: '700' }], variable: '--font-kalam', display: 'swap' });

export default function RootLayout({children}:Readonly<{children:React.ReactNode}>) {return <html lang="en" className={`${nunito.variable} ${instrument.variable} ${caveat.variable} ${kalam.variable}`}><body>{children}</body></html>;}
