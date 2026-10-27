import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import ContactPage from "@/app/contact/page";
import Footer from "./Footer";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

describe("status links", () => {
  it("links the public status page from the footer and the contact page", () => {
    expect(renderToStaticMarkup(<Footer />)).toContain('href="/status"');
    expect(renderToStaticMarkup(<ContactPage />)).toContain('href="/status"');
  });
});
