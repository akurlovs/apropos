import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="blocked">
        <h2>Something went wrong displaying this page</h2>
        <p>No figures are shown. <button onClick={() => location.reload()}>Reload</button></p>
      </div>
    );
  }
}
