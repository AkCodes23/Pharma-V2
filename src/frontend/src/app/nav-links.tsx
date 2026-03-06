'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard' },
  { href: '/reports', label: 'Reports' },
  { href: '/admin', label: 'Operations' },
];

export function NavLinks() {
  const pathname = usePathname();

  return (
    <>
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={`nav-link ${pathname === item.href ? 'nav-link--active' : ''}`}
        >
          {item.label}
        </Link>
      ))}
    </>
  );
}
