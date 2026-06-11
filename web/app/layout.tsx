import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Option Strategy Backtests",
  description: "Backtest results for option trading strategies",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-gray-800 bg-gray-950">
          <div className="mx-auto max-w-6xl px-4 py-4">
            <Link href="/" className="text-lg font-semibold text-gray-100">
              Option Strategy Backtests
            </Link>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
