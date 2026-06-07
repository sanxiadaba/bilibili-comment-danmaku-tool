import { useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

type VirtualListProps<T> = {
  className?: string;
  empty?: ReactNode;
  estimateSize: number;
  getKey: (item: T, index: number) => string;
  items: T[];
  overscan?: number;
  renderItem: (item: T, index: number) => ReactNode;
};

type MeasuredRowProps = {
  children: ReactNode;
  measureKey: string;
  onMeasure: (key: string, size: number) => void;
  top: number;
};

export function VirtualList<T>({
  className,
  empty,
  estimateSize,
  getKey,
  items,
  overscan = 6,
  renderItem,
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const [sizes, setSizes] = useState<Record<string, number>>({});

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const updateViewport = () => setViewportHeight(element.clientHeight);
    updateViewport();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateViewport);
      return () => window.removeEventListener("resize", updateViewport);
    }

    const observer = new ResizeObserver(updateViewport);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const metrics = useMemo(() => {
    const offsets: number[] = [];
    const rowSizes: number[] = [];
    let totalSize = 0;

    items.forEach((item, index) => {
      const key = getKey(item, index);
      const size = sizes[key] || estimateSize;
      offsets[index] = totalSize;
      rowSizes[index] = size;
      totalSize += size;
    });

    return { offsets, rowSizes, totalSize };
  }, [estimateSize, getKey, items, sizes]);

  const visibleRange = useMemo(() => {
    if (!items.length) return { start: 0, end: -1 };
    const viewportBottom = scrollTop + viewportHeight;
    let low = 0;
    let high = items.length - 1;
    let first = 0;

    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      if (metrics.offsets[middle] + metrics.rowSizes[middle] >= scrollTop) {
        first = middle;
        high = middle - 1;
      } else {
        low = middle + 1;
      }
    }

    let last = first;
    while (last < items.length - 1 && metrics.offsets[last] < viewportBottom) {
      last += 1;
    }

    return {
      start: Math.max(0, first - overscan),
      end: Math.min(items.length - 1, last + overscan),
    };
  }, [items.length, metrics.offsets, metrics.rowSizes, overscan, scrollTop, viewportHeight]);

  const visibleItems = useMemo(() => {
    if (visibleRange.end < visibleRange.start) return [];
    return items.slice(visibleRange.start, visibleRange.end + 1).map((item, offset) => ({
      index: visibleRange.start + offset,
      item,
    }));
  }, [items, visibleRange.end, visibleRange.start]);

  const handleMeasure = useCallback((key: string, size: number) => {
    setSizes((current) => {
      if (Math.abs((current[key] || 0) - size) < 1) return current;
      return { ...current, [key]: size };
    });
  }, []);

  const handleScroll = useCallback(() => {
    setScrollTop(containerRef.current?.scrollTop || 0);
  }, []);

  if (!items.length) {
    return <div className={className}>{empty}</div>;
  }

  return (
    <div className={className} ref={containerRef} onScroll={handleScroll}>
      <div className="relative w-full" style={{ height: metrics.totalSize }}>
        {visibleItems.map(({ item, index }) => {
          const key = getKey(item, index);
          return (
            <MeasuredRow
              key={key}
              measureKey={key}
              onMeasure={handleMeasure}
              top={metrics.offsets[index] || 0}
            >
              {renderItem(item, index)}
            </MeasuredRow>
          );
        })}
      </div>
    </div>
  );
}

function MeasuredRow({ children, measureKey, onMeasure, top }: MeasuredRowProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;

    const measure = () => onMeasure(measureKey, element.getBoundingClientRect().height);
    measure();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }

    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measureKey, onMeasure]);

  return (
    <div className="absolute left-0 right-0 top-0" ref={ref} style={{ transform: `translateY(${top}px)` }}>
      {children}
    </div>
  );
}
