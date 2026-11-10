import { Component, type ErrorInfo, type ReactNode } from "react";

type ErrorBoundaryProps = {
  children: ReactNode;
};

type ErrorBoundaryState = {
  error: Error | null;
};

/**
 * Without a boundary a single unexpected API payload unmounts the whole tree and the user is
 * left with a white page. Keep the failure visible and recoverable instead.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("unhandled render error", error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null });
  };

  private goHome = () => {
    window.location.assign("/");
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-xl rounded-md border border-line bg-white p-6 shadow-soft">
          <h1 className="text-lg font-semibold text-ink">页面渲染出错</h1>
          <p className="mt-2 text-sm text-muted">
            这通常是本地数据或接口返回的字段不符合预期。可以重试，或回到视频库继续操作。
          </p>
          <pre className="mt-3 max-h-40 overflow-auto rounded bg-slate-50 p-3 text-xs text-slate-600">
            {this.state.error.message}
          </pre>
          <div className="mt-4 flex gap-2">
            <button className="btn-primary h-10 rounded-md px-4 text-sm font-medium" type="button" onClick={this.reset}>
              重试
            </button>
            <button className="btn-quiet h-10 rounded-md px-4 text-sm font-medium" type="button" onClick={this.goHome}>
              返回视频库
            </button>
          </div>
        </div>
      </div>
    );
  }
}
