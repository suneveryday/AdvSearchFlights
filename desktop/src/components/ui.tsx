import { useEffect, useRef } from "react";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
};

export function Button({ className, variant = "secondary", size = "md", ...props }: ButtonProps) {
  return <button className={cx("ui-button", `ui-button-${variant}`, `ui-button-${size}`, className)} {...props} />;
}

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: LucideIcon;
  label: string;
  selected?: boolean;
  status?: "default" | "ok" | "warning" | "error" | "checking";
};

export function IconButton({ icon: Icon, label, className, selected, status = "default", ...props }: IconButtonProps) {
  return (
    <button
      type="button"
      className={cx("ui-icon-button", selected && "selected", `status-${status}`, className)}
      aria-label={label}
      title={label}
      {...props}
    >
      <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
    </button>
  );
}

export function SidebarItem({ icon: Icon, label, active, badge, onClick }: { icon: LucideIcon; label: string; active?: boolean; badge?: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className={cx("ui-sidebar-item", active && "active")} aria-current={active ? "page" : undefined} onClick={onClick}>
      <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
      <span>{label}</span>
      {badge ? <span className="ui-sidebar-badge">{badge}</span> : null}
    </button>
  );
}

export function StatusBadge({ tone = "neutral", children, className }: { tone?: "neutral" | "accent" | "success" | "warning" | "danger"; children: ReactNode; className?: string }) {
  return <span className={cx("ui-status-badge", `tone-${tone}`, className)}>{children}</span>;
}

export function EmptyState({ icon: Icon, title, description, action }: { icon: LucideIcon; title: string; description: string; action?: ReactNode }) {
  return (
    <section className="ui-empty-state">
      <div className="ui-empty-icon"><Icon size={30} strokeWidth={1.5} aria-hidden="true" /></div>
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </section>
  );
}

export function DialogShell({ title, description, children, footer, onClose, className, labelledBy }: { title: string; description?: string; children: ReactNode; footer?: ReactNode; onClose: () => void; className?: string; labelledBy: string }) {
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    dialogRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
  return (
    <div className="ui-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section ref={dialogRef} tabIndex={-1} className={cx("ui-dialog", className)} role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        <header className="ui-dialog-header">
          <div><strong id={labelledBy}>{title}</strong>{description ? <span>{description}</span> : null}</div>
          <button type="button" className="ui-dialog-close" aria-label="关闭" title="关闭" onClick={onClose}>×</button>
        </header>
        <div className="ui-dialog-content">{children}</div>
        {footer ? <footer className="ui-dialog-footer">{footer}</footer> : null}
      </section>
    </div>
  );
}

export function SettingsGroup({ title, children }: { title: string; children: ReactNode }) {
  return <section className="ui-settings-group"><h2>{title}</h2><div>{children}</div></section>;
}

export function SettingsRow({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <label className="ui-settings-row"><span><strong>{title}</strong>{description ? <small>{description}</small> : null}</span><span className="ui-settings-control">{children}</span></label>;
}

export function SectionHeader({ title, description, actions, className }: { title: string; description?: string; actions?: ReactNode; className?: string }) {
  return <header className={cx("ui-section-header", className)}><div><h1>{title}</h1>{description ? <p>{description}</p> : null}</div>{actions ? <div className="ui-section-actions">{actions}</div> : null}</header>;
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("ui-skeleton", className)} aria-hidden="true" {...props} />;
}
