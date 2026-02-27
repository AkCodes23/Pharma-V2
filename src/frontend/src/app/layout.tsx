import type { Metadata } from 'next';
import './globals.css';
import { NavLinks } from './nav-links';

export const metadata: Metadata = {
  title: 'Pharma Agentic AI — Strategic Command Center',
  description: 'Distributed multi-agent pharmaceutical intelligence platform. Real-time patent analysis, clinical trial monitoring, market intelligence, and safety signal detection.',
  keywords: ['pharma', 'AI', 'patent cliff', 'generic drugs', 'clinical trials', 'market intelligence'],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="header">
          <div className="header__logo">
            <div className="header__logo-icon">🧬</div>
            <div>
              <div className="header__title">Pharma Agentic AI</div>
              <div className="header__subtitle">Strategic Command Center</div>
            </div>
          </div>
          <nav style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <NavLinks />
            <span className="status-indicator status-indicator--healthy" title="System healthy" />
          </nav>
        </header>
        <main className="app-container">
          {children}
        </main>
        <footer className="footer">
          <span>v0.1.0 • Pharma Agentic AI</span>
          <span style={{ margin: '0 0.5rem' }}>•</span>
          <span className="footer__badge">🔒 21 CFR Part 11</span>
        </footer>
      </body>
    </html>
  );
}
