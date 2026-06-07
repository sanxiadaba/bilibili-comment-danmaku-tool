import { useEffect, useState } from "react";
import { DanmakuPage } from "./pages/DanmakuPage";
import { VideoDetailPage } from "./pages/VideoDetailPage";
import { VideoLibraryPage } from "./pages/VideoLibraryPage";

function App() {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const syncPath = () => setPath(window.location.pathname);
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, []);

  const danmakuMatch = path.match(/^\/danmaku\/(BV[0-9A-Za-z]{10})/);
  if (danmakuMatch) {
    return <DanmakuPage bvid={danmakuMatch[1]} />;
  }

  const detailMatch = path.match(/^\/video\/(BV[0-9A-Za-z]{10})/);
  if (detailMatch) {
    return <VideoDetailPage bvid={detailMatch[1]} />;
  }

  return <VideoLibraryPage />;
}

export default App;
