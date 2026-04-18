export function Login() {
  return (
    <div style={{ padding: 48, fontFamily: "system-ui, sans-serif" }}>
      <h1>team-pivot-web</h1>
      <p>Sign in with Feishu to continue.</p>
      <a
        href="/login"
        style={{
          display: "inline-block",
          padding: "10px 20px",
          background: "#3370ff",
          color: "white",
          borderRadius: 6,
          textDecoration: "none",
        }}
      >
        Sign in with Feishu
      </a>
    </div>
  );
}
