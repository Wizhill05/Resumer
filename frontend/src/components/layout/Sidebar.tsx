"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";

const NAV = [
  { href: "/studio",  label: "Resume Studio" },
  { href: "/profile", label: "Master Profile" },
  { href: "/jobs",    label: "Find Jobs" },
  { href: "/batch",   label: "Batch Processing" },
  { href: "/tracker", label: "Apply Tracker" },
] as const;

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-44 flex-shrink-0 bg-neutral-900 border-r border-neutral-800 flex flex-col">
      <div className="px-4 py-3 border-b border-neutral-800">
        <span className="text-sm font-bold tracking-widest text-neutral-100">RESUMER</span>
      </div>
      <nav className="flex-1 py-2">
        {NAV.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={clsx(
              "block px-4 py-2 text-xs leading-tight",
              pathname.startsWith(href)
                ? "bg-neutral-800 text-white"
                : "text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800/50"
            )}
          >
            {label}
          </Link>
        ))}
      </nav>
      <div className="px-4 py-2 border-t border-neutral-800">
        <span className="text-xs text-neutral-600">v2.0 nextjs</span>
      </div>
    </aside>
  );
}
