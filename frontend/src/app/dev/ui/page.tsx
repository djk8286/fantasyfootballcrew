import type { Metadata } from "next";
import Showcase from "./Showcase";

export const metadata: Metadata = {
  title: "UI components | Fantasy Football Crew",
  robots: { index: false, follow: false },
};

export default function DevUiPage() {
  return <Showcase />;
}
