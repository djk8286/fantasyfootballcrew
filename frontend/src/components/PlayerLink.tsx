import Link from "next/link";

/** A player's name, linking to their /players/[id] page. Used in place
 * of a plain name <span> in player rows sitewide -- only the name is the
 * link, so row controls (Add / Start / Bench, hover cards) keep working. */
export default function PlayerLink({
  id,
  children,
  className = "",
}: {
  id: string | null | undefined;
  children: React.ReactNode;
  className?: string;
}) {
  if (!id) return <span className={className}>{children}</span>;
  return (
    <Link href={`/players/${id}`} className={`${className} hover:text-gold-400 hover:underline underline-offset-2 transition-colors`}>
      {children}
    </Link>
  );
}
