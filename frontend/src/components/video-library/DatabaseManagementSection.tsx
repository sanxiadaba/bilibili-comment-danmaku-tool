import type React from "react";
import { ManagementPanel } from "./ManagementPanel";
import type { ManagementView } from "./types";
import type { DatabaseInfo, ProgressQueue } from "../../types";

type DatabaseManagementSectionProps = {
  activeDbId: string;
  databases: DatabaseInfo[];
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  folderInputRef: React.RefObject<HTMLInputElement | null>;
  hotplugDir: string;
  importPath: string;
  isImporting: boolean;
  isLoading: boolean;
  legacyExportDir: string;
  queue?: ProgressQueue;
  view: ManagementView;
  onFilesSelected: (files: FileList | null, source: "file" | "folder") => void;
  onImportPathChange: (value: string) => void;
  onRefresh: () => void;
  onSelect: (dbId: string, reload?: boolean) => void;
  onSubmitImport: (event: React.FormEvent<HTMLFormElement>) => void;
  onViewChange: (view: ManagementView) => void;
};

export function DatabaseManagementSection({
  activeDbId,
  databases,
  fileInputRef,
  folderInputRef,
  hotplugDir,
  importPath,
  isImporting,
  isLoading,
  legacyExportDir,
  queue,
  view,
  onFilesSelected,
  onImportPathChange,
  onRefresh,
  onSelect,
  onSubmitImport,
  onViewChange,
}: DatabaseManagementSectionProps) {
  return (
    <section className="mx-auto max-w-[1540px] px-4 pb-4 lg:px-6">
      <ManagementPanel
        activeDbId={activeDbId}
        databases={databases}
        hotplugDir={hotplugDir}
        importPath={importPath}
        isImporting={isImporting}
        isLoading={isLoading}
        legacyExportDir={legacyExportDir}
        queue={queue}
        view={view}
        onImportPathChange={onImportPathChange}
        onPickFiles={() => fileInputRef.current?.click()}
        onPickFolder={() => folderInputRef.current?.click()}
        onRefresh={onRefresh}
        onSelect={onSelect}
        onViewChange={onViewChange}
        onSubmitImport={onSubmitImport}
      />
      <input
        ref={fileInputRef}
        className="hidden"
        type="file"
        accept=".db,.sqlite,.sqlite3,.json"
        multiple
        onChange={(event) => onFilesSelected(event.target.files, "file")}
      />
      <input
        ref={folderInputRef}
        className="hidden"
        type="file"
        accept=".db,.sqlite,.sqlite3,.json"
        multiple
        // @ts-expect-error Chromium supports folder selection via webkitdirectory.
        webkitdirectory="true"
        onChange={(event) => onFilesSelected(event.target.files, "folder")}
      />
    </section>
  );
}
