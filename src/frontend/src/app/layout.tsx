import type { Metadata } from 'next';

import './globals.css';
import { NavLinks } from './nav-links';

export const metadata: Metadata = {
  title: 'Pharma Agentic AI | Standalone Demo',
  description:
    'Offline pharmaceutical strategy workspace for market-entry intelligence, retrieval progress, and downloadable demo reports.',
  keywords: ['pharma', 'demo', 'market intelligence', 'clinical trials', 'patent strategy'],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <div className="shell-rim" />
          <header className="header">
            <div className="header__brand">
              <div className="brand-mark" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <div>
                <div className="header__title">Pharma Agentic AI</div>
                <div className="header__subtitle">Standalone Strategy Console</div>
              </div>
            </div>
            <nav className="header__nav" aria-label="Primary">
              <NavLinks />
              <div className="runtime-chip">
                <span className="runtime-chip__dot" />
                Demo mode
              </div>
            </nav>
          </header>
          <main className="app-container">{children}</main>
          <footer className="footer">
            <span>Standalone demo branch</span>
            <span className="footer__divider" />
            <span>Offline fixtures</span>
            <span className="footer__divider" />
            <span>Local report artifacts</span>
          </footer>
        </div>
      </body>
    </html>
  );
}
