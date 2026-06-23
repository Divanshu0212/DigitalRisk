export default function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <header className="page-head">
      {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
      <div className="grid" style={{ gap: 10 }}>
        <h1>{title}</h1>
        {description ? <p className="page-copy">{description}</p> : null}
      </div>
      {actions ? <div className="row">{actions}</div> : null}
    </header>
  );
}