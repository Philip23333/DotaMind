import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MetaMind",
  description: "Composable esports intelligence agent for Dota2 meta reports.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
