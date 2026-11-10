/** Знак Tochno: аркуш з галочкою і маркером. Колір знака фіксований (бренд), слово — currentColor. */
export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="9" fill="#0E7C5A" />
      <path d="M10 6.5h8.2L24.5 13v12.5a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2v-17a2 2 0 0 1 2-2Z" fill="#F6F3EA" />
      <path d="M18.2 6.5V11a2 2 0 0 0 2 2h4.3" fill="#BFE0D1" />
      <path d="M12 19.4l3.1 3.1 5.9-6.4" fill="none" stroke="#0E7C5A" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="23.6" cy="6.4" r="2.4" fill="#F4C430" />
    </svg>
  )
}

export function Logo({ size = 28, suffix }: { size?: number; suffix?: string }) {
  return (
    <span className="logo" aria-label={`Tochno${suffix ? ' ' + suffix : ''}`}>
      <Mark size={size} />
      <span className="logo-word">Tochno</span>
      {suffix && <span className="logo-suffix">{suffix}</span>}
    </span>
  )
}
