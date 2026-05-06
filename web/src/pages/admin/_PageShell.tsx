/** Common page wrapper for /admin/* sub-routes:
 *  consistent max-width, padding, and a top header (title + optional
 *  description). Section components (WorkspaceConfigSection,
 *  AISettingsSection, etc.) render below this header.
 *
 *  Default width is 4xl (form pages). Pass `wide` for table-heavy
 *  pages like Matter 评分's runs list (7 columns need ≥7xl). */
export function PageShell({
  title,
  description,
  children,
  wide = false,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`mx-auto w-full ${wide ? "max-w-7xl" : "max-w-4xl"} px-4 py-5 sm:p-6 lg:p-8`}>
      <header className="mb-5 sm:mb-6">
        <h1
          className="m-0 text-[22px] sm:text-[24px]"
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
            className="mt-2 max-w-2xl text-[13px] leading-[1.65] sm:text-[13.5px]"
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
