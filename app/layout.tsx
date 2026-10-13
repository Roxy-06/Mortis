import "./globals.css";
import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "MORTIS // Algorithmic Trading & Portfolio Intelligence",
  description: "Institutional-grade algorithmic trading dashboard featuring live market analytics, position sizing calculators, and threshold frequency evaluation.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark scroll-smooth">
      <body 
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased bg-[#080d0b] text-white min-h-screen selection:bg-theme-lime selection:text-black`}
      >
        <div className="relative min-h-screen flex flex-col">
          {children}
        </div>
      </body>
    </html>
  );
}
