import type { Metadata } from "next";
import StatusBoard from "./StatusBoard";

export const metadata: Metadata = {
  title: "System status | Fantasy Football Crew",
  description: "Whether Fantasy Football Crew is up, and how fresh the Sleeper and ESPN sync is.",
};

export default function StatusPage() {
  return <StatusBoard />;
}
