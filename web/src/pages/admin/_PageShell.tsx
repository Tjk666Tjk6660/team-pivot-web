/** Common page wrapper for /admin/* sub-routes:
 *  consistent max-width, padding, and a top header (title + optional
 *  description). Section components (WorkspaceConfigSection,
 *  AISettingsSection, etc.) render below this header. */
export function PageShell({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-4xl p-6 lg:p-8">
      <header className="mb-6">
        <h1
          className="m-0 text-[24px]"
          style={{
            fontFamily: "var(--font-serif)",
            fontWeight: 600,
            letterSpacing: "var(--letter-tight)",
            color: "var(--text)",
          }}
        >
          {title}
        </h1>
        {description && (
          <p
            className="mt-2 text-[13.5px] leading-[1.65]"
            style={{
              fontFamily: "var(--font-serif)",
              color: "var(--text-soft)",
            }}
          >
            {description}
          </p>
        )}
      </header>
      <div className="space-y-6">{children}</div>
    </div>
  );
}
