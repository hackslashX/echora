import type { Metadata } from "next";
import Backdrop from "@/components/shell/Backdrop";
import { PlayerProvider } from "@/components/player/PlayerProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Echora",
  description: "A personal map of your music",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body><div className="app-viewport"><Backdrop /><PlayerProvider>{children}</PlayerProvider></div></body>
    </html>
  );
}
