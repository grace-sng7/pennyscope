// Pennyscope's mascot: a little coin wearing glasses. Decorative only.
export function Coin({ size = 32, className }: { size?: number; className?: string }) {
  return <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 40 40" className={className}>
    <circle cx="20" cy="21" r="17" fill="#C9962E" />
    <circle cx="20" cy="19.5" r="17" fill="#EBC35A" stroke="#1D2333" strokeWidth="1.6" />
    <circle cx="20" cy="19.5" r="13" fill="none" stroke="#B7832A" strokeWidth="1.2" strokeDasharray="2 2.4" />
    <path d="M9 11.5c2.5-3.2 6-5 9.5-5.3" fill="none" stroke="#FFF3C4" strokeWidth="2" strokeLinecap="round" />
    <circle cx="14.2" cy="18.5" r="4.4" fill="#FFFDF8" fillOpacity=".55" stroke="#1D2333" strokeWidth="1.8" />
    <circle cx="25.8" cy="18.5" r="4.4" fill="#FFFDF8" fillOpacity=".55" stroke="#1D2333" strokeWidth="1.8" />
    <path d="M18.6 18c.9-.8 1.9-.8 2.8 0" fill="none" stroke="#1D2333" strokeWidth="1.6" strokeLinecap="round" />
    <path d="M9.8 17.6 7.4 16.4M30.2 17.6l2.4-1.2" stroke="#1D2333" strokeWidth="1.6" strokeLinecap="round" />
    <circle cx="14.6" cy="18.9" r="1.5" fill="#1D2333" />
    <circle cx="26.2" cy="18.9" r="1.5" fill="#1D2333" />
    <path d="M16.5 26c1.9 1.6 5.1 1.6 7 0" fill="none" stroke="#1D2333" strokeWidth="1.6" strokeLinecap="round" />
  </svg>;
}
