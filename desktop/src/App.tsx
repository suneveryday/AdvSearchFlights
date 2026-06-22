import { Fragment, FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlarmClock,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  Command,
  ExternalLink,
  History,
  LoaderCircle,
  Moon,
  Plane,
  RefreshCw,
  Search,
  Settings,
  SlidersHorizontal,
  Sun,
  Trash2,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { buildGuiSearchPayload, defaultSearchForm, validatePayload } from "./searchPayload";
import { configureHistorySchedule, configureScheduler, deleteHistoryGroup, getAlertPermissionStatus, getAppSettings, getHistoryGroup, getHistoryGroupResults, listHistoryGroups, openExternalUrl, runNetworkCheck, startGuiSearch, subscribeScheduleEvents, toggleHistorySchedule, updateAppSettings } from "./searchClient";
import { analyticsAvailable, captureAnalytics, captureAppOpened, configureAnalytics, durationBucket, networkAnalyticsProperties, normalizedErrorCategory, resultCountBucket } from "./analytics";
import { scheduleDraftForGroup, validateScheduleDraft } from "./scheduleSettings";
import type { ScheduleDraft } from "./scheduleSettings";
import { visibleNetworkModules, visibleNetworkStatus } from "./networkPresentation";
import { Button, DialogShell, EmptyState, IconButton, SettingsGroup, SettingsRow, SidebarItem, StatusBadge, cx } from "./components/ui";
import type {
  FlightSegment,
  GuiSearchEnvelope,
  AppSettings,
  AlertPermissionStatus,
  HistoryFilters,
  HistoryGroup,
  HistoryGroupResults,
  NetworkCheckResult,
  RenderedResult,
  SearchFormState,
  SearchProgressEvent,
} from "./types";

type ViewState = "idle" | "loading" | "results" | "empty" | "error";
type SortKey = "price" | "airline" | "departure" | "arrival" | "route" | "layover" | "layoverCity";
type SortDirection = "asc" | "desc";
type WorkspaceMode = "search" | "history";
type ThemeMode = "light" | "dark";
type ResultFilterOptions = HistoryGroupResults["filter_options"];

const emptyHistoryFilters: HistoryFilters = {
  max_total_price: null,
  include_airlines: [],
  exclude_airlines: [],
  airport_routes: [],
  max_stops_per_leg: null,
  max_single_layover_hours: null,
  exclude_layover_airports: [],
  departure_time_range: null,
  arrival_time_range: null,
};

function App() {
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("search");
  const [historySidebarTarget, setHistorySidebarTarget] = useState<HTMLDivElement | null>(null);
  const [form, setForm] = useState<SearchFormState>(defaultSearchForm);
  const [viewState, setViewState] = useState<ViewState>("idle");
  const [envelope, setEnvelope] = useState<GuiSearchEnvelope | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [events, setEvents] = useState<SearchProgressEvent[]>([]);
  const [activeTask, setActiveTask] = useState<{ cancel: () => Promise<void>; cleanup: () => void } | null>(null);
  const [network, setNetwork] = useState<NetworkCheckResult | null>(null);
  const [networkLoading, setNetworkLoading] = useState(false);
  const [networkDialogOpen, setNetworkDialogOpen] = useState(false);
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [analyticsConsentOpen, setAnalyticsConsentOpen] = useState(false);
  const [analyticsSaving, setAnalyticsSaving] = useState(false);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = globalThis.localStorage?.getItem("adv-search-flights-theme");
    if (saved === "light" || saved === "dark") return saved;
    return globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [sortKey, setSortKey] = useState<SortKey>("price");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [searchFilters, setSearchFilters] = useState<HistoryFilters>(emptyHistoryFilters);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const originInputRef = useRef<HTMLInputElement>(null);
  const searchStartedAt = useRef<number | null>(null);
  const scheduledSearchStartedAt = useRef(new Map<string, number>());
  const appOpenedCaptured = useRef(false);
  const payload = useMemo(() => buildGuiSearchPayload(form), [form]);
  const displayedNetworkStatus = visibleNetworkStatus(network);

  useEffect(() => {
    void getAppSettings().then((settings) => {
      setAppSettings(settings);
      const restoredForm = {
        ...defaultSearchForm,
        httpProxy: settings.http_proxy,
        allProxy: settings.all_proxy,
      };
      setForm((current) => ({ ...current, httpProxy: settings.http_proxy, allProxy: settings.all_proxy }));
      void refreshNetwork(buildGuiSearchPayload(restoredForm), false, "startup").then(async (result) => {
        if (result?.auto_configured) {
          const latestSettings = await getAppSettings();
          setAppSettings(latestSettings);
          const latestForm = { ...restoredForm, httpProxy: latestSettings.http_proxy, allProxy: latestSettings.all_proxy };
          setForm((current) => ({ ...current, httpProxy: latestSettings.http_proxy, allProxy: latestSettings.all_proxy }));
          await configureScheduler(buildGuiSearchPayload(latestForm));
        }
      });
      configureAnalytics(settings);
      if (settings.analytics_consent === "unset" && analyticsAvailable()) setAnalyticsConsentOpen(true);
      if (settings.analytics_consent === "granted" && !appOpenedCaptured.current) {
        captureAppOpened();
        appOpenedCaptured.current = true;
      }
    }).catch(() => { void refreshNetwork(buildGuiSearchPayload(defaultSearchForm), false, "startup"); });
  }, []);

  useEffect(() => {
    if (appSettings?.analytics_consent !== "granted") return;
    captureAnalytics("farello_workspace_viewed", { workspace: workspaceMode });
    if (workspaceMode === "history") captureAnalytics("farello_history_opened", {});
  }, [workspaceMode, appSettings?.analytics_consent]);

  useEffect(() => {
    let cleanup: () => void = () => undefined;
    void subscribeScheduleEvents(({ group_id, event }) => {
      if (event.type === "started") {
        scheduledSearchStartedAt.current.set(group_id, Date.now());
        captureAnalytics("farello_search_started", { source: "scheduled" });
      }
      if (event.type === "completed" && event.envelope) {
        const count = event.envelope.response?.rendered.length ?? 0;
        const startedAt = scheduledSearchStartedAt.current.get(group_id) ?? Date.now();
        scheduledSearchStartedAt.current.delete(group_id);
        captureAnalytics("farello_search_finished", {
          source: "scheduled",
          outcome: count > 0 ? "results" : "empty",
          result_count_bucket: resultCountBucket(count),
          duration_bucket: durationBucket(Date.now() - startedAt),
        });
      }
      if (event.type === "failed") {
        scheduledSearchStartedAt.current.delete(group_id);
        captureAnalytics("farello_search_failed", { source: "scheduled", error_category: normalizedErrorCategory(event.message || "") });
      }
      if (event.type === "notification_sent" || event.type === "notification_failed") {
        const channel = event.channel === "reminders" ? "reminders" : "desktop";
        captureAnalytics("farello_alert_delivery", { channel, outcome: event.type === "notification_sent" ? "success" : "failure" });
      }
    }).then((unlisten) => { cleanup = unlisten; });
    return () => cleanup();
  }, []);

  useEffect(() => {
    void configureScheduler(payload);
  }, [payload]);

  useEffect(() => {
    return () => activeTask?.cleanup();
  }, [activeTask]);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    document.documentElement.style.colorScheme = themeMode;
    globalThis.localStorage?.setItem("adv-search-flights-theme", themeMode);
  }, [themeMode]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.metaKey) return;
      if (event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen(true);
      } else if (event.key === ",") {
        event.preventDefault();
        setSettingsDialogOpen(true);
      } else if (event.key.toLowerCase() === "f") {
        event.preventDefault();
        setWorkspaceMode("search");
        globalThis.setTimeout(() => originInputRef.current?.focus(), 0);
      }
    };
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, []);

  function updateField<K extends keyof SearchFormState>(key: K, value: SearchFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function refreshNetwork(nextPayload = payload, showDialog = true, mode: "startup" | "manual" = showDialog ? "manual" : "startup") {
    if (showDialog) setNetworkDialogOpen(true);
    setNetworkLoading(true);
    try {
      const result = await runNetworkCheck(nextPayload, mode);
      setNetwork(result);
      captureAnalytics("farello_network_check_finished", networkAnalyticsProperties(result, showDialog ? "manual" : "startup"));
      return result;
    } catch (error) {
      setNetwork({
        status: "error",
        modules: [{ name: "network_check", label: "网络检测", status: "error", ok: false, message: errorMessage(error) }],
        guide_status: "error",
      });
      return null;
    } finally {
      setNetworkLoading(false);
    }
  }

  async function runSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = validatePayload(payload);
    setErrors(nextErrors);
    if (nextErrors.length > 0) {
      setEnvelope(null);
      setViewState("error");
      captureAnalytics("farello_search_failed", { source: "manual", error_category: "validation" });
      return;
    }
    searchStartedAt.current = Date.now();
    captureAnalytics("farello_search_started", { source: "manual" });
    activeTask?.cleanup();
    setSearchFilters(emptyHistoryFilters);
    setEvents([
      {
        type: "client_started",
        provider: payload.provider,
        message: `已提交搜索：数据源 ${payload.provider}，${payload.origin}->${payload.destinations.join(" / ")}`,
      },
    ]);
    setEnvelope(null);
    setViewState("loading");
    try {
      const task = await startGuiSearch(payload, handleProgressEvent);
      setActiveTask(task);
    } catch (error) {
      setErrors([errorMessage(error)]);
      setViewState("error");
      captureAnalytics("farello_search_failed", { source: "manual", error_category: normalizedErrorCategory(errorMessage(error)) });
    }
  }

  async function cancelSearch() {
    if (!activeTask) return;
    try {
      await activeTask.cancel();
      activeTask.cleanup();
      setActiveTask(null);
      setViewState("error");
      setErrors(["搜索已取消"]);
      captureAnalytics("farello_search_cancelled", { source: "manual" });
    } catch (error) {
      setErrors([`取消搜索失败：${errorMessage(error)}`]);
    }
  }

  function handleProgressEvent(event: SearchProgressEvent) {
    setEvents((current) => [...current.slice(-30), event]);
    const nextNetworkStatus = event.network_status;
    if (nextNetworkStatus) {
      setEnvelope((current) => current ? { ...current, network_status: nextNetworkStatus } : current);
    }
    if (event.type === "completed" && event.envelope) {
      setEnvelope(event.envelope);
      setActiveTask((task) => {
        task?.cleanup();
        return null;
      });
      if (!event.envelope.ok) {
        setErrors(event.envelope.error ? [event.envelope.error.message] : ["搜索失败"]);
        setViewState("error");
        captureAnalytics("farello_search_failed", { source: "manual", error_category: normalizedErrorCategory(event.envelope.error?.message || "") });
        return;
      }
      if (event.envelope.provider_status.status === "error") {
        setErrors(statusMessages(event.envelope));
        setViewState("error");
        captureAnalytics("farello_search_failed", { source: "manual", error_category: "provider" });
        return;
      }
      const count = event.envelope.response?.rendered.length ?? 0;
      captureAnalytics("farello_search_finished", {
        source: "manual",
        outcome: count > 0 ? "results" : "empty",
        result_count_bucket: resultCountBucket(count),
        duration_bucket: durationBucket(Date.now() - (searchStartedAt.current ?? Date.now())),
      });
      setViewState(count ? "results" : "empty");
    }
    if (event.type === "failed") {
      setErrors([event.message || "搜索失败"]);
      setActiveTask((task) => {
        task?.cleanup();
        return null;
      });
      setViewState("error");
      captureAnalytics("farello_search_failed", { source: "manual", error_category: normalizedErrorCategory(event.message || "") });
    }
  }

  async function setAnalyticsConsent(consent: AppSettings["analytics_consent"]) {
    if (!appSettings || analyticsSaving) return;
    setAnalyticsSaving(true);
    setAnalyticsError(null);
    try {
      const settings = await updateAppSettings({ analytics_consent: consent });
      setAppSettings(settings);
      configureAnalytics(settings);
      setAnalyticsConsentOpen(false);
      if (consent === "granted" && !appOpenedCaptured.current) {
        captureAppOpened();
        appOpenedCaptured.current = true;
      }
    } catch (error) {
      setAnalyticsError(errorMessage(error));
    } finally {
      setAnalyticsSaving(false);
    }
  }

  async function saveSettingsAndClose() {
    if (settingsSaving) return;
    setSettingsSaving(true);
    setSettingsError(null);
    try {
      const settings = await updateAppSettings({
        http_proxy: form.httpProxy.trim(),
        all_proxy: form.allProxy.trim(),
      });
      const nextForm = { ...form, httpProxy: settings.http_proxy, allProxy: settings.all_proxy };
      const nextPayload = buildGuiSearchPayload(nextForm);
      setAppSettings(settings);
      setForm(nextForm);
      await configureScheduler(nextPayload);
      await refreshNetwork(nextPayload, false, "manual");
      setSettingsDialogOpen(false);
    } catch (error) {
      setSettingsError(errorMessage(error));
    } finally {
      setSettingsSaving(false);
    }
  }

  const allRows = envelope?.response?.rendered ?? [];
  const filterOptions = useMemo(() => buildResultFilterOptions(allRows), [allRows]);
  const tableRows = useMemo(() => sortAndFilter(allRows, sortKey, sortDirection, searchFilters), [
    allRows,
    sortKey,
    sortDirection,
    searchFilters,
  ]);

  async function openPurchaseLink(url: string) {
    try {
      await openExternalUrl(url);
    } catch (error) {
      setErrors([errorMessage(error)]);
      setViewState("error");
    }
  }

  return (
    <div className={`app-shell ${workspaceMode === "history" ? "history-mode" : "search-mode"}`}>
      <aside className="sidebar">
        <header className="sidebar-heading" data-tauri-drag-region>
          <div className="sidebar-toolbar-title" data-tauri-drag-region>
            <strong>工作区</strong>
            <span>搜索与历史记录</span>
          </div>
        </header>
        <nav className="workspace-nav" aria-label="工作区">
          <SidebarItem icon={Search} label="航班搜索" active={workspaceMode === "search"} onClick={() => setWorkspaceMode("search")} />
          <SidebarItem icon={History} label="搜索历史" active={workspaceMode === "history"} onClick={() => setWorkspaceMode("history")} />
        </nav>
        {workspaceMode === "search" ? <form className="search-form" onSubmit={runSearch}>
          <div className="form-section">
            <h2>行程</h2>
            <label className="field-control">
              <span>出发地</span>
              <input ref={originInputRef} aria-label="出发地" value={form.origin} onChange={(event) => updateField("origin", event.target.value)} />
            </label>
            <label className="field-control">
              <span>目的地</span>
              <input aria-label="目的地候选" className="destinations-input" value={form.destinationsText} onChange={(event) => updateField("destinationsText", event.target.value)} />
            </label>
            <div className="two-col date-grid">
              <label><span>去程</span><input aria-label="去程日期" type="date" value={form.departure} onChange={(event) => updateField("departure", event.target.value)} /></label>
              <label><span>回程</span><input aria-label="回程日期" type="date" value={form.returnDate} onChange={(event) => updateField("returnDate", event.target.value)} /></label>
            </div>
          </div>

          <div className="form-section">
            <h2>搜索条件</h2>
            <div className="constraint-grid">
              <label className="constraint-field"><span>舱位</span><select aria-label="舱位" value={form.cabinClass} onChange={(event) => updateField("cabinClass", event.target.value as SearchFormState["cabinClass"])}><option value="ECONOMY">经济舱</option><option value="PREMIUM_ECONOMY">超级经济舱</option><option value="BUSINESS">商务舱</option><option value="FIRST">头等舱</option></select></label>
              <label className="constraint-field"><span>结果数量</span><span className="number-input"><input aria-label="结果数量" type="number" min="0" max="50" value={form.limit} onChange={(event) => updateField("limit", Number(event.target.value))} /><small>{form.limit === 0 ? "全部" : "条"}</small></span></label>
              <label className="constraint-field"><span>每程最多中转</span><span className="number-input"><input aria-label="最大中转" type="number" min="0" max="3" value={form.maxStops} onChange={(event) => updateField("maxStops", Number(event.target.value))} /><small>次</small></span></label>
              <label className="constraint-field"><span>最长中转时间</span><span className="number-input"><input aria-label="最长中转时间" type="number" min="0" step="0.5" value={form.maxLayoverHours} onChange={(event) => updateField("maxLayoverHours", Number(event.target.value))} /><small>小时</small></span></label>
            </div>
            <div className="form-actions">
              <Button type="submit" variant="primary" disabled={viewState === "loading"}>{viewState === "loading" ? <><LoaderCircle className="spin" size={15} />搜索中</> : <><Search size={15} />开始搜索</>}</Button>
              {viewState === "loading" ? <Button type="button" onClick={cancelSearch}>取消搜索</Button> : null}
            </div>
          </div>
        </form> : <div className="history-sidebar-slot" ref={setHistorySidebarTarget} />}
      </aside>

      <main className={`workspace${workspaceMode === "history" ? " history-workspace-mode" : ""}`}>
        <div className="workspace-toolbar" data-tauri-drag-region>
          <div className="toolbar-title" data-tauri-drag-region>
            <strong>{workspaceMode === "search" ? "航班结果" : "搜索历史"}</strong>
            <span>{workspaceMode === "search" ? "比较价格、时刻与中转方案" : "查看价格变化和已保存结果"}</span>
          </div>
          <div className="tools">
            <IconButton icon={Command} label="命令菜单（⌘K）" onClick={() => setCommandPaletteOpen(true)} />
            <IconButton icon={themeMode === "dark" ? Sun : Moon} label={themeMode === "dark" ? "切换到浅色模式" : "切换到深色模式"} onClick={() => setThemeMode((current) => current === "dark" ? "light" : "dark")} />
            <IconButton
              icon={networkLoading ? LoaderCircle : displayedNetworkStatus === "error" ? WifiOff : Wifi}
              className={networkLoading ? "spin-icon" : undefined}
              status={networkLoading ? "checking" : displayedNetworkStatus === "ok" ? "ok" : displayedNetworkStatus === "error" ? "error" : "warning"}
              label={`网络检测：${networkLoading ? "检测中" : displayedNetworkStatus || "未知"}`}
              onClick={() => refreshNetwork(payload, true)}
            />
            <IconButton icon={Settings} label="高级设置（⌘,）" onClick={() => setSettingsDialogOpen(true)} />
          </div>
        </div>
        {workspaceMode === "history" ? <HistoryWorkspace sidebarTarget={historySidebarTarget} onOpenLink={openPurchaseLink} /> : <>
        {viewState === "idle" ? <EmptyState icon={Plane} title="准备搜索航班" description="在左侧设置行程与筛选条件，搜索进度和结果会显示在这里。" /> : null}
        {viewState !== "idle" ? <ResultsSummary
          rows={allRows}
          currentCount={envelope?.response?.rendered.length ?? 0}
          form={form}
        /> : null}
        {viewState !== "idle" && viewState !== "results" && viewState !== "loading" ? <StatusPanel state={viewState} errors={errors} envelope={envelope} /> : null}
        {viewState === "loading" ? <ProgressPanel events={events} /> : null}
        {viewState === "results" && allRows.length > 0 ? (
          <ResultsTable
            rows={tableRows}
            filterOptions={filterOptions}
            sortKey={sortKey}
            sortDirection={sortDirection}
            filters={searchFilters}
            expanded={expanded}
            onSort={(key) => {
              setSortDirection((current) => (sortKey === key && current === "asc" ? "desc" : "asc"));
              setSortKey(key);
            }}
            onFiltersChange={setSearchFilters}
            onToggle={(rank) => setExpanded((current) => ({ ...current, [rank]: !current[rank] }))}
            onOpenLink={openPurchaseLink}
          />
        ) : null}
        {viewState === "results" && envelope ? <JsonDetails envelope={envelope} /> : null}
        </>}
      </main>
      {networkDialogOpen ? (
        <NetworkDialog
          result={network}
          loading={networkLoading}
          onRefresh={() => refreshNetwork(payload, true)}
          onClose={() => setNetworkDialogOpen(false)}
        />
      ) : null}
      {settingsDialogOpen ? (
        <SettingsDialog
          form={form}
          appSettings={appSettings}
          analyticsAvailable={analyticsAvailable()}
          analyticsSaving={analyticsSaving}
          analyticsError={analyticsError}
          settingsSaving={settingsSaving}
          settingsError={settingsError}
          onUpdate={updateField}
          onAnalyticsChange={(enabled) => void setAnalyticsConsent(enabled ? "granted" : "denied")}
          onClose={saveSettingsAndClose}
        />
      ) : null}
      {commandPaletteOpen ? <CommandPalette
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={(mode) => { setWorkspaceMode(mode); setCommandPaletteOpen(false); }}
        onOpenSettings={() => { setCommandPaletteOpen(false); setSettingsDialogOpen(true); }}
        onCheckNetwork={() => { setCommandPaletteOpen(false); void refreshNetwork(payload, true); }}
      /> : null}
      {analyticsConsentOpen ? <AnalyticsConsentDialog
        loading={analyticsSaving}
        error={analyticsError}
        onDeny={() => void setAnalyticsConsent("denied")}
        onAllow={() => void setAnalyticsConsent("granted")}
      /> : null}
    </div>
  );
}

function HistoryWorkspace({ sidebarTarget, onOpenLink }: { sidebarTarget: HTMLDivElement | null; onOpenLink: (url: string) => void }) {
  const [groups, setGroups] = useState<HistoryGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [data, setData] = useState<HistoryGroupResults | null>(null);
  const [filters, setFilters] = useState<HistoryFilters>(emptyHistoryFilters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("price");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [scheduleGroup, setScheduleGroup] = useState<HistoryGroup | null>(null);
  const [scheduleDraft, setScheduleDraft] = useState<ScheduleDraft | null>(null);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [permissionStatus, setPermissionStatus] = useState<AlertPermissionStatus | null>(null);
  const resultRequestId = useRef(0);

  useEffect(() => {
    void loadGroups();
  }, []);

  useEffect(() => {
    let cleanup: () => void = () => undefined;
    void subscribeScheduleEvents((payload) => {
      const warning = payload.event.type === "notification_failed"
        ? `${payload.event.channel === "reminders" ? "Apple Reminders" : "桌面通知"}发送失败：${payload.event.message || "请检查系统权限"}`
        : null;
      void loadGroups(selectedGroupId).then(() => {
        if (warning) setNotice(warning);
      });
    }).then((unlisten) => { cleanup = unlisten; });
    return () => cleanup();
  }, [selectedGroupId]);

  async function loadGroups(preferredId?: string | null) {
    setLoading(true);
    setError(null);
    try {
      const items = await listHistoryGroups();
      setGroups(items);
      const nextId = preferredId && items.some((item) => item.id === preferredId) ? preferredId : items[0]?.id ?? null;
      setSelectedGroupId(nextId);
      if (nextId) {
        await loadResults(nextId, null, emptyHistoryFilters);
      } else {
        setData(null);
      }
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }

  async function loadResults(groupId: string, batchId: string | null, nextFilters: HistoryFilters) {
    const requestId = ++resultRequestId.current;
    setLoading(true);
    setError(null);
    try {
      const item = await getHistoryGroupResults(groupId, batchId, nextFilters);
      if (requestId !== resultRequestId.current) return;
      setData(item);
      setExpanded({});
    } catch (nextError) {
      if (requestId !== resultRequestId.current) return;
      setError(errorMessage(nextError));
    } finally {
      if (requestId === resultRequestId.current) setLoading(false);
    }
  }

  async function selectGroup(groupId: string) {
    setDeleteDialogOpen(false);
    setDeleteError(null);
    setSelectedGroupId(groupId);
    setFilters(emptyHistoryFilters);
    await loadResults(groupId, null, emptyHistoryFilters);
  }

  async function applyFilters(nextFilters: HistoryFilters) {
    if (!selectedGroupId) return;
    setFilters(nextFilters);
    await loadResults(selectedGroupId, data?.selected_batch.id ?? null, nextFilters);
  }

  async function removeSelectedGroup() {
    if (!selectedGroupId || !data) return;
    setDeleteLoading(true);
    setDeleteError(null);
    try {
      const deleted = await deleteHistoryGroup(selectedGroupId);
      if (!deleted) throw new Error("历史组不存在或已经删除");
      const { remaining, next } = nextHistoryGroupAfterDeletion(groups, selectedGroupId);
      setGroups(remaining);
      setFilters(emptyHistoryFilters);
      setSelectedGroupId(next?.id ?? null);
      if (next) await loadResults(next.id, null, emptyHistoryFilters);
      else setData(null);
      setDeleteDialogOpen(false);
    } catch (nextError) {
      setDeleteError(errorMessage(nextError));
    } finally {
      setDeleteLoading(false);
    }
  }

  async function openScheduleSettings(group: HistoryGroup) {
    setError(null);
    setNotice(null);
    setScheduleError(null);
    setPermissionStatus(null);
    setScheduleGroup(group);
    setScheduleDraft(scheduleDraftForGroup(group));
    try {
      const detail = await getHistoryGroup(group.id);
      const latestPrice = detail?.batches[0]?.minimum_price_cny ?? null;
      setScheduleDraft(scheduleDraftForGroup(group, latestPrice));
      if (group.schedule_notification_enabled) {
        setPermissionStatus(await getAlertPermissionStatus(true));
      }
    } catch (nextError) {
      setScheduleError(errorMessage(nextError));
    }
  }

  async function setNotificationEnabled(enabled: boolean) {
    setScheduleDraft((current) => current ? { ...current, notificationEnabled: enabled } : current);
    if (!enabled) return;
    try {
      setPermissionStatus(await getAlertPermissionStatus(true));
    } catch (nextError) {
      setPermissionStatus({ desktop: "error", reminders: "denied", reminders_message: errorMessage(nextError) });
    }
  }

  async function saveSchedule() {
    if (!scheduleGroup || !scheduleDraft) return;
    const validation = validateScheduleDraft(scheduleDraft);
    if (validation.length) { setScheduleError(validation[0]); return; }
    setScheduleSaving(true);
    setScheduleError(null);
    try {
      const permissionWarning = scheduleDraft.notificationEnabled
        ? [
          permissionStatus?.desktop === "denied" || permissionStatus?.desktop === "error" ? "macOS 桌面通知" : null,
          permissionStatus?.reminders === "denied" || permissionStatus?.reminders === "error" ? "Apple Reminders" : null,
        ].filter(Boolean).join("、")
        : "";
      await configureHistorySchedule(
        scheduleGroup.id,
        scheduleDraft.intervalHours,
        scheduleDraft.notificationEnabled,
        scheduleDraft.notificationEnabled ? scheduleDraft.priceThreshold : null,
      );
      captureAnalytics("farello_schedule_configured", {
        interval_hours: scheduleDraft.intervalHours,
        notification_enabled: scheduleDraft.notificationEnabled,
      });
      setScheduleGroup(null);
      setScheduleDraft(null);
      await loadGroups(selectedGroupId ?? scheduleGroup.id);
      if (permissionWarning) setNotice(`${permissionWarning}尚未获得权限；定时搜索已启用，价格提醒发送可能失败。请在系统设置中检查权限。`);
    } catch (nextError) {
      setScheduleError(errorMessage(nextError));
    } finally {
      setScheduleSaving(false);
    }
  }

  async function disableSchedule() {
    if (!scheduleGroup) return;
    setScheduleSaving(true);
    setScheduleError(null);
    try {
      await toggleHistorySchedule(scheduleGroup.id, false);
      captureAnalytics("farello_schedule_disabled", {});
      setScheduleGroup(null);
      setScheduleDraft(null);
      await loadGroups(selectedGroupId ?? scheduleGroup.id);
    } catch (nextError) {
      setScheduleError(errorMessage(nextError));
    } finally {
      setScheduleSaving(false);
    }
  }

  const tableRows = useMemo(
    () => [...(data?.rendered ?? [])].sort((a, b) => compareRows(a, b, sortKey) * (sortDirection === "asc" ? 1 : -1)),
    [data?.rendered, sortKey, sortDirection],
  );
  return (
    <>
      {sidebarTarget ? createPortal(<div className="history-groups">
        <header><div><strong>搜索历史</strong><span>{groups.length} 组 · 本地保存</span></div></header>
        <div className="history-group-list">
          {groups.map((group) => {
            const scheduled = Boolean(group.schedule_enabled);
            return <div key={group.id} className={`history-group-item${selectedGroupId === group.id ? " active" : ""}${scheduled ? " scheduled" : ""}`}>
              <button type="button" className="schedule-button" aria-label={scheduled ? "编辑定时自动搜索" : "定时自动搜索"} title={scheduleTooltip(group)} onClick={(event) => { event.stopPropagation(); void openScheduleSettings(group); }}><AlarmClock size={15} strokeWidth={1.8} aria-hidden="true" /></button>
              <button type="button" className="history-group-main" onClick={() => selectGroup(group.id)}>
                <strong>{group.title}</strong>
                <span>{group.date_label}</span>
                <small>{cabinLabel(group.cabin_class)} · {group.adults} 人 · 中转 ≤ {group.max_stops} · 停留 ≤ {group.max_layover_hours}h</small>
                <small>{group.currency} · {group.batch_count ?? 0} 次搜索{scheduled ? ` · ${scheduleStatusLabel(group.schedule_status)}` : ""}</small>
              </button>
            </div>;
          })}
          {!loading && groups.length === 0 ? <EmptyState icon={History} title="暂无搜索历史" description="完成一次真实数据源搜索后，结果会自动保存在这里。" /> : null}
        </div>
      </div>, sidebarTarget) : null}
    <section className="history-workspace">
      <div className="history-detail">
        {error ? <StateMessage tone="danger" icon={AlertTriangle} title="无法读取搜索历史" description={error} /> : null}
        {notice ? <StateMessage tone="warning" icon={AlertTriangle} title="提醒权限需要检查" description={notice} /> : null}
        {loading && !data ? <LoadingState label="正在读取本地历史" /> : null}
        {!loading && !data && !error ? <EmptyState icon={History} title="选择一条搜索历史" description="从左侧列表选择历史航线，查看价格趋势和保存的航班结果。" /> : null}
        {data ? <>
          <div className="history-sticky">
            <header className="history-condition-summary">
              <div><span>历史航线</span><h1>{data.group.title}</h1><p>{data.group.date_label}</p></div>
              <div className="condition-tags"><span>{cabinLabel(data.group.cabin_class)}</span><span>{data.group.adults} 人</span><span>中转 ≤ {data.group.max_stops}</span><span>停留 ≤ {data.group.max_layover_hours}h</span><span>{data.group.currency}</span></div>
              <button type="button" className="danger-text-button" onClick={() => { setDeleteError(null); setDeleteDialogOpen(true); }}><Trash2 size={13} aria-hidden="true" />删除此组</button>
            </header>
            <PriceTrend key={data.group.id} points={data.trend} selectedBatchId={data.selected_batch.id} />
            <div className="history-batches" aria-label="历史搜索批次">
              {data.batches.map((batch) => {
                const timestamp = formatHistoryBatchTimestamp(batch.created_at);
                return <button type="button" key={batch.id} className={batch.id === data.selected_batch.id ? "active" : ""} onClick={() => loadResults(data.group.id, batch.id, filters)}><strong>{timestamp.date}</strong><span>{timestamp.time}</span><b>{batch.minimum_price_cny == null ? "无结果" : `¥${batch.minimum_price_cny}`}</b></button>;
              })}
            </div>
          </div>
          <div className="history-result-heading"><strong>{formatHistoryTimestamp(data.selected_batch.created_at)}</strong><span>{data.result_count} 条符合当前筛选</span>{loading ? <small>更新中…</small> : null}</div>
          <ResultsTable
            rows={tableRows}
            filterOptions={data.filter_options}
            sortKey={sortKey}
            sortDirection={sortDirection}
            filters={filters}
            expanded={expanded}
            onSort={(key) => { setSortDirection((current) => sortKey === key && current === "asc" ? "desc" : "asc"); setSortKey(key); }}
            onFiltersChange={applyFilters}
            onToggle={(rank) => setExpanded((current) => ({ ...current, [rank]: !current[rank] }))}
            onOpenLink={onOpenLink}
          />
        </> : null}
      </div>
    </section>
    {deleteDialogOpen && data ? <DeleteGroupDialog
      title={data.group.title}
      batchCount={data.batches.length}
      loading={deleteLoading}
      error={deleteError}
      onCancel={() => { if (!deleteLoading) setDeleteDialogOpen(false); }}
      onConfirm={removeSelectedGroup}
    /> : null}
    {scheduleGroup && scheduleDraft ? <ScheduleSettingsDialog
      group={scheduleGroup}
      draft={scheduleDraft}
      permissionStatus={permissionStatus}
      loading={scheduleSaving}
      error={scheduleError}
      onDraftChange={setScheduleDraft}
      onNotificationChange={setNotificationEnabled}
      onCancel={() => { if (!scheduleSaving) { setScheduleGroup(null); setScheduleDraft(null); } }}
      onDisable={disableSchedule}
      onConfirm={saveSchedule}
    /> : null}
    </>
  );
}

export function nextHistoryGroupAfterDeletion(groups: HistoryGroup[], selectedId: string): { remaining: HistoryGroup[]; next: HistoryGroup | null } {
  const selectedIndex = groups.findIndex((item) => item.id === selectedId);
  const remaining = groups.filter((item) => item.id !== selectedId);
  const index = selectedIndex < 0 ? 0 : selectedIndex;
  return { remaining, next: remaining[index] ?? remaining[index - 1] ?? null };
}

function DeleteGroupDialog({ title, batchCount, loading, error, onCancel, onConfirm }: { title: string; batchCount: number; loading: boolean; error: string | null; onCancel: () => void; onConfirm: () => void }) {
  return <DialogShell
    title="删除搜索历史组"
    description={title}
    labelledBy="delete-group-title"
    className="delete-group-dialog"
    onClose={onCancel}
    footer={<><Button disabled={loading} onClick={onCancel}>取消</Button><Button variant="danger" disabled={loading} onClick={onConfirm}>{loading ? "删除中…" : "确认删除"}</Button></>}
  >
    <StateMessage tone="danger" icon={Trash2} title={`将删除 ${batchCount} 个搜索批次`} description="该组的航线结果会被永久删除，此操作不可撤销。" />
    {error ? <div className="delete-error" role="alert">{error}</div> : null}
  </DialogShell>;
}

function ScheduleSettingsDialog({ group, draft, permissionStatus, loading, error, onDraftChange, onNotificationChange, onCancel, onDisable, onConfirm }: {
  group: HistoryGroup;
  draft: ScheduleDraft;
  permissionStatus: AlertPermissionStatus | null;
  loading: boolean;
  error: string | null;
  onDraftChange: (draft: ScheduleDraft) => void;
  onNotificationChange: (enabled: boolean) => Promise<void>;
  onCancel: () => void;
  onDisable: () => void;
  onConfirm: () => void;
}) {
  const permissionTone = (status?: string): "neutral" | "success" | "warning" | "danger" => {
    if (status === "granted" || status === "allowed") return "success";
    if (status === "denied" || status === "error") return "danger";
    if (status === "prompt" || status === "prompt-with-rationale") return "warning";
    return "neutral";
  };
  const permissionLabel = (status?: string) => ({
    granted: "已允许",
    allowed: "已允许",
    denied: "未允许",
    error: "检查失败",
    prompt: "待确认",
    "prompt-with-rationale": "待确认",
    unchecked: "未检查",
  })[status || "unchecked"] || status || "未检查";

  return <DialogShell
    title="定时自动搜索"
    description={group.title}
    labelledBy="schedule-settings-title"
    className="schedule-settings-dialog"
    onClose={onCancel}
    footer={<>
      {group.schedule_enabled ? <Button variant="danger" disabled={loading} onClick={onDisable}>关闭定时搜索</Button> : null}
      <span className="dialog-footer-spacer" />
      <Button disabled={loading} onClick={onCancel}>取消</Button>
      <Button variant="primary" disabled={loading} onClick={onConfirm}>{loading ? "保存中…" : "确认并立即搜索"}</Button>
    </>}
  >
    <div className="schedule-settings-content">
      <div className="schedule-overview">
        <span className="schedule-overview-icon"><AlarmClock size={18} strokeWidth={1.8} aria-hidden="true" /></span>
        <span><strong>{group.schedule_enabled ? "编辑自动搜索计划" : "创建自动搜索计划"}</strong><small>确认后立即搜索一次，之后按设定间隔自动执行。</small></span>
      </div>
      <SettingsGroup title="执行计划">
        <SettingsRow title="自动搜索间隔" description="确认后立即搜索一次，之后按此间隔执行">
          <select value={draft.intervalHours} onChange={(event) => onDraftChange({ ...draft, intervalHours: Number(event.target.value) })}>
            {Array.from({ length: 48 }, (_, index) => index + 1).map((hours) => <option key={hours} value={hours}>{hours} 小时</option>)}
          </select>
        </SettingsRow>
      </SettingsGroup>
      <SettingsGroup title="价格提醒">
        <SettingsRow title="低价提醒" description="定时搜索的最低总价严格低于阈值时提醒">
          <label className="ui-switch">
            <input type="checkbox" checked={draft.notificationEnabled} onChange={(event) => void onNotificationChange(event.target.checked)} />
            <span className="ui-switch-track" aria-hidden="true"><span /></span>
            <span className="ui-switch-label">{draft.notificationEnabled ? "开启" : "关闭"}</span>
          </label>
        </SettingsRow>
        {draft.notificationEnabled ? <SettingsRow title="提醒价格阈值" description={`币种：${group.currency}`}>
          <div className="schedule-price-control"><span>¥</span><input type="number" min="1" step="1" value={draft.priceThreshold ?? ""} onChange={(event) => onDraftChange({ ...draft, priceThreshold: event.target.value ? Number(event.target.value) : null })} /></div>
        </SettingsRow> : null}
      </SettingsGroup>
      {draft.notificationEnabled ? <SettingsGroup title="提醒权限">
        <div className="schedule-permission-row"><span><strong>macOS 桌面通知</strong><small>显示航线、最低价和提醒阈值</small></span><StatusBadge tone={permissionTone(permissionStatus?.desktop)}>{permissionLabel(permissionStatus?.desktop)}</StatusBadge></div>
        <div className="schedule-permission-row"><span><strong>Apple Reminders</strong><small>在 Farello 列表中创建或更新提醒事项</small></span><StatusBadge tone={permissionTone(permissionStatus?.reminders)}>{permissionLabel(permissionStatus?.reminders)}</StatusBadge></div>
        {permissionStatus?.reminders_message ? <p className="permission-warning" role="alert">{permissionStatus.reminders_message}</p> : null}
        <div className="schedule-guidance"><AlertTriangle size={14} aria-hidden="true" /><p>请检查“系统设置 → 通知 → Farello”以及“系统设置 → 隐私与安全性 → 自动化 → Reminders”。权限失败不会中断定时搜索。</p></div>
      </SettingsGroup> : null}
      {error ? <div className="delete-error" role="alert">{error}</div> : null}
    </div>
  </DialogShell>;
}

function PriceTrend({ points, selectedBatchId }: { points: HistoryGroupResults["trend"]; selectedBatchId: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return undefined;
    const scrollToLatest = () => { node.scrollLeft = node.scrollWidth; };
    scrollToLatest();
    const observer = new ResizeObserver(scrollToLatest);
    observer.observe(node);
    return () => observer.disconnect();
  }, [points.length]);
  const prices = points.flatMap((point) => point.minimum_price_cny == null ? [] : [point.minimum_price_cny]);
  const min = prices.length ? Math.min(...prices) : 0;
  const max = prices.length ? Math.max(...prices) : 1;
  const chartWidth = Math.max(460, points.length * 104);
  const x = (index: number) => 52 + index * 104;
  const y = (price: number) => 58 - ((price - min) / Math.max(1, max - min)) * 30;
  return <div className="price-trend"><div className="trend-heading"><strong>最低价格趋势</strong><span>{points.length} 次搜索</span></div><div ref={scrollRef} className="price-trend-scroll"><svg width={chartWidth} height="96" viewBox={`0 0 ${chartWidth} 96`} role="img" aria-label="历史最低价格趋势">
    <line x1="24" y1="64" x2={chartWidth - 24} y2="64" className="trend-axis" />
    {points.slice(1).map((point, index) => {
      const previous = points[index];
      if (previous.minimum_price_cny == null || point.minimum_price_cny == null) return null;
      return <line key={`${previous.batch_id}-${point.batch_id}`} x1={x(index)} y1={y(previous.minimum_price_cny)} x2={x(index + 1)} y2={y(point.minimum_price_cny)} className="trend-line" />;
    })}
    {points.map((point, index) => {
      const pointY = point.minimum_price_cny == null ? 64 : y(point.minimum_price_cny);
      const selected = point.batch_id === selectedBatchId;
      return <g key={point.batch_id} className={selected ? "trend-point selected" : "trend-point"}>
        <circle cx={x(index)} cy={pointY} r={selected ? 4 : 3} className={point.minimum_price_cny == null ? "trend-gap" : "trend-dot"} />
        <text x={x(index)} y={Math.max(12, pointY - 9)} className="trend-price-label" textAnchor="middle">{point.minimum_price_cny == null ? "无结果" : `¥${point.minimum_price_cny}`}</text>
        <text x={x(index)} y="82" className="trend-date-label" textAnchor="middle">{formatTrendTimestamp(point.created_at)}</text>
      </g>;
    })}
  </svg></div></div>;
}

function cabinLabel(value: string): string {
  return { ECONOMY: "经济舱", PREMIUM_ECONOMY: "超级经济舱", BUSINESS: "商务舱", FIRST: "头等舱" }[value] ?? value;
}

function scheduleStatusLabel(status: HistoryGroup["schedule_status"]): string {
  return {
    scheduled: "已定时",
    queued: "等待执行",
    running: "搜索中",
    rate_limited_wait: "等待重试",
    succeeded: "上次成功",
    failed: "上次失败",
    paused_expired: "行程已过期",
    disabled: "已关闭",
  }[status || "scheduled"] || "已定时";
}

function scheduleTooltip(group: HistoryGroup): string {
  if (!group.schedule_enabled) return "定时自动搜索";
  if (group.schedule_status === "paused_expired") return "定时自动搜索已暂停：去程日期已过期";
  if (group.schedule_status === "rate_limited_wait") return "定时自动搜索正在等待限频重试";
  return group.schedule_next_run_at ? `编辑定时自动搜索 · 下次 ${formatHistoryTimestamp(group.schedule_next_run_at)}` : "编辑定时自动搜索";
}

function formatHistoryTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value.slice(0, 16).replace("T", " ") : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export function formatHistoryBatchTimestamp(value: string): { date: string; time: string } {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { date: value.slice(5, 10), time: value.slice(11, 16) };
  const parts = new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return { date: `${part("month")}-${part("day")}`, time: `${part("hour")}:${part("minute")}` };
}

function formatTrendTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(5, 16).replace("T", " ");
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

function NetworkDialog({ result, loading, onRefresh, onClose }: { result: NetworkCheckResult | null; loading: boolean; onRefresh: () => void; onClose: () => void }) {
  const statusTone = (status?: string): "success" | "danger" | "warning" | "neutral" => status === "ok" ? "success" : status === "error" ? "danger" : status === "warning" ? "warning" : "neutral";
  const modules = visibleNetworkModules(result);
  return <DialogShell
    title="网络检测"
    description={loading ? "正在检查本机代理和 Google Flights" : "确认搜索所需的代理与 Google Flights 状态"}
    labelledBy="network-dialog-title"
    className="network-dialog"
    onClose={onClose}
    footer={<><Button onClick={onClose}>关闭</Button><Button variant="primary" disabled={loading} onClick={onRefresh}>{loading ? <><LoaderCircle className="spin" size={15} />检测中</> : <><RefreshCw size={15} />重新检测</>}</Button></>}
  >
    <div className="network-list">
      {modules.map((item) => (
        <div key={item.name} className="network-row">
          <span className="network-row-icon">{item.status === "ok" ? <CheckCircle2 /> : item.status === "error" ? <AlertTriangle /> : <Clock3 />}</span>
          <span><strong>{item.label}</strong><small>{item.message}</small></span>
          <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
        </div>
      ))}
      {!result ? <LoadingState label={loading ? "正在运行网络检测" : "等待网络检测"} compact /> : null}
    </div>
  </DialogShell>;
}

function CommandPalette({ onClose, onNavigate, onOpenSettings, onCheckNetwork }: { onClose: () => void; onNavigate: (mode: WorkspaceMode) => void; onOpenSettings: () => void; onCheckNetwork: () => void }) {
  return <DialogShell title="快速操作" description="使用键盘快速切换工作区和常用工具" labelledBy="command-palette-title" className="command-palette" onClose={onClose}>
    <div className="command-list">
      <button type="button" onClick={() => onNavigate("search")}><Search /><span><strong>航班搜索</strong><small>打开搜索条件与结果</small></span><kbd>⌘F</kbd></button>
      <button type="button" onClick={() => onNavigate("history")}><History /><span><strong>搜索历史</strong><small>查看价格趋势与已保存结果</small></span></button>
      <button type="button" onClick={onCheckNetwork}><Wifi /><span><strong>检查网络</strong><small>检测代理与 Google Flights</small></span></button>
      <button type="button" onClick={onOpenSettings}><Settings /><span><strong>高级设置</strong><small>代理与搜索执行设置</small></span><kbd>⌘,</kbd></button>
    </div>
  </DialogShell>;
}

function LoadingState({ label, compact = false }: { label: string; compact?: boolean }) {
  return <div className={cx("ui-loading-state", compact && "compact")} role="status"><LoaderCircle className="spin" size={compact ? 16 : 22} aria-hidden="true" /><span>{label}</span></div>;
}

function StateMessage({ tone, icon: Icon, title, description }: { tone: "neutral" | "success" | "warning" | "danger"; icon: LucideIcon; title: string; description?: string }) {
  return <section className={cx("ui-state-message", `tone-${tone}`)} role={tone === "danger" ? "alert" : "status"}><Icon size={18} strokeWidth={1.8} aria-hidden="true" /><div><strong>{title}</strong>{description ? <p>{description}</p> : null}</div></section>;
}

function SettingsDialog({
  form,
  appSettings,
  analyticsAvailable: analyticsEnabled,
  analyticsSaving,
  analyticsError,
  settingsSaving,
  settingsError,
  onUpdate,
  onAnalyticsChange,
  onClose,
}: {
  form: SearchFormState;
  appSettings: AppSettings | null;
  analyticsAvailable: boolean;
  analyticsSaving: boolean;
  analyticsError: string | null;
  settingsSaving: boolean;
  settingsError: string | null;
  onUpdate: <K extends keyof SearchFormState>(key: K, value: SearchFormState[K]) => void;
  onAnalyticsChange: (enabled: boolean) => void;
  onClose: () => void | Promise<void>;
}) {
  const proxyConfigured = Boolean(form.httpProxy.trim() || form.allProxy.trim());
  return <DialogShell title="高级设置" description="网络代理与搜索执行策略" labelledBy="settings-dialog-title" className="settings-dialog" onClose={() => void onClose()} footer={<Button variant="primary" disabled={settingsSaving} onClick={() => void onClose()}>{settingsSaving ? "保存中…" : "完成"}</Button>}>
    <div className="settings-content">
      <SettingsGroup title="网络代理">
        <SettingsRow title="HTTP / HTTPS" description="留空时先尝试直连 Google Flights，失败后自动检测可用代理。"><input className="proxy-input" value={form.httpProxy} placeholder="例如：http://127.0.0.1:7893" onChange={(event) => onUpdate("httpProxy", event.target.value)} /></SettingsRow>
        <SettingsRow title="ALL_PROXY" description="支持 socks5 代理。"><input className="proxy-input" value={form.allProxy} placeholder="例如：socks5://127.0.0.1:7894" onChange={(event) => onUpdate("allProxy", event.target.value)} /></SettingsRow>
        {!proxyConfigured ? <p className="settings-note settings-error">当前未保存代理。首次启动会先尝试直连 Google Flights；失败后才自动检测本地代理。</p> : <p className="settings-note">代理将在点击“完成”后保存，并用于网络检测、手动搜索和定时搜索。</p>}
        {settingsError ? <p className="settings-note settings-error" role="alert">{settingsError}</p> : null}
      </SettingsGroup>
      <SettingsGroup title="执行策略">
        <SettingsRow title="单段超时" description="单个航段请求的最长等待时间。"><input type="number" min="5" value={form.fliTimeoutSeconds} onChange={(event) => onUpdate("fliTimeoutSeconds", Number(event.target.value))} /><span className="control-suffix">秒</span></SettingsRow>
        <SettingsRow title="总超时" description="整次搜索任务的最长等待时间。"><input type="number" min="30" value={form.guiTimeoutSeconds} onChange={(event) => onUpdate("guiTimeoutSeconds", Number(event.target.value))} /><span className="control-suffix">秒</span></SettingsRow>
        <SettingsRow title="并发查询" description="保守设置可以降低触发限频的概率。"><input type="number" min="1" max="6" value={form.maxConcurrentSearches} onChange={(event) => onUpdate("maxConcurrentSearches", Number(event.target.value))} /></SettingsRow>
      </SettingsGroup>
      <SettingsGroup title="隐私与统计">
        <SettingsRow title="匿名使用统计" description="仅发送功能使用与错误类别，不发送航线、日期、机场、价格、输入内容或搜索结果。">
          <label className="ui-switch">
            <input
              type="checkbox"
              checked={appSettings?.analytics_consent === "granted"}
              disabled={!analyticsEnabled || !appSettings || analyticsSaving}
              onChange={(event) => onAnalyticsChange(event.target.checked)}
            />
            <span className="ui-switch-track" aria-hidden="true"><span /></span>
            <span className="ui-switch-label">{appSettings?.analytics_consent === "granted" ? "开启" : "关闭"}</span>
          </label>
        </SettingsRow>
        {!analyticsEnabled ? <p className="settings-note">当前构建未配置匿名统计服务，不会发送任何数据。</p> : null}
        {analyticsError ? <p className="settings-note settings-error" role="alert">{analyticsError}</p> : null}
      </SettingsGroup>
    </div>
  </DialogShell>;
}

function AnalyticsConsentDialog({ loading, error, onDeny, onAllow }: { loading: boolean; error: string | null; onDeny: () => void; onAllow: () => void }) {
  return <DialogShell
    title="帮助改进 Farello"
    description="匿名使用统计由你决定"
    labelledBy="analytics-consent-title"
    className="analytics-consent-dialog"
    onClose={onDeny}
    footer={<><Button disabled={loading} onClick={onDeny}>暂不允许</Button><Button variant="primary" disabled={loading} onClick={onAllow}>{loading ? "保存中…" : "允许匿名统计"}</Button></>}
  >
    <div className="analytics-consent-content">
      <StateMessage tone="neutral" icon={CheckCircle2} title="只了解产品是否好用" description="统计启动、工作区切换、搜索结果区间、耗时区间、标准化错误类别，以及定时搜索和提醒是否成功。" />
      <div className="privacy-never-list">
        <strong>绝不采集</strong>
        <p>航线、日期、机场、价格、搜索输入和结果、历史记录、购买链接、原始错误、姓名、邮箱、账号或硬件标识。</p>
      </div>
      <p className="privacy-footnote">Farello 使用随机匿名安装 ID。你可以随时在“设置 → 隐私与统计”中关闭。</p>
      {error ? <p className="settings-note settings-error" role="alert">{error}</p> : null}
    </div>
  </DialogShell>;
}

function ResultsSummary({
  rows,
  currentCount,
  form,
}: {
  rows: RenderedResult[];
  currentCount: number;
  form: SearchFormState;
}) {
  const lowest = rows.length ? Math.min(...rows.map((row) => row.total_price_cny)) : null;
  const destinations = form.destinationsText.split(/[,，\s]+/).filter(Boolean).join(" / ");
  const activeBatch = `${form.origin} → ${destinations || "目的地"}`;
  return (
    <section className="results-summary">
      <div className="summary-route"><span>当前搜索</span><strong>{activeBatch}</strong></div>
      <dl className="summary-metrics"><div><dt>匹配结果</dt><dd>{rows.length || currentCount || 0}</dd></div><div><dt>最低价格</dt><dd>{lowest ? `¥${lowest}` : "-"}</dd></div></dl>
    </section>
  );
}

function StatusPanel({ state, errors, envelope }: { state: ViewState; errors: string[]; envelope: GuiSearchEnvelope | null }) {
  if (state === "idle") return <StateMessage tone="neutral" icon={Plane} title="输入参数后运行搜索" />;
  if (state === "loading") return <StateMessage tone="neutral" icon={LoaderCircle} title="正在搜索航班" description="任务拆解和当前航段会实时显示在下方。" />;
  if (state === "empty") return <div><StateMessage tone="warning" icon={AlertTriangle} title={emptyResultMessage(envelope)} /><MessageList items={statusMessages(envelope)} /></div>;
  if (state === "error") return <div><StateMessage tone="danger" icon={AlertTriangle} title="搜索未完成" description={errors[0] || "请检查输入后重试。"} />{errors.length > 1 ? <MessageList items={errors.slice(1)} /> : null}</div>;
  return <StateMessage tone="success" icon={CheckCircle2} title={`已返回 ${envelope?.response?.result_count ?? 0} 个组合结果`} description={`网络：${networkLabel(envelope)} · 数据源：${envelope?.provider_status.status}`} />;
}

function emptyResultMessage(envelope: GuiSearchEnvelope | null): string {
  if (!envelope) return "搜索完成，但没有返回结果。";
  const warnings = [...envelope.provider_status.warnings, ...(envelope.response?.warnings ?? [])];
  if (warnings.length > 0) return envelope.provider_status.message || "搜索完成，但所有航段都被过滤或失败。";
  if (envelope.provider_status.provider === "fli") {
    return "fli 数据源本次没有返回可组合航班，不是表格展示过滤导致。可以稍后重试，或放宽中转/停留条件。";
  }
  return envelope.provider_status.message || "搜索完成，但没有符合当前筛选条件的结果。";
}

function ProgressPanel({ events }: { events: SearchProgressEvent[] }) {
  const [expanded, setExpanded] = useState(false);
  const latest = events[events.length - 1];
  const countdown = useRetryCountdown(latest?.type === "retry_waiting" ? latest.retry_at : undefined);
  const completed = latest?.completed ?? 0;
  const total = latest?.total ?? 0;
  const failures = events.filter((event) => event.type === "leg_failed").length;
  return (
    <section className="progress-panel" aria-live="polite">
      <header>
        <div className="progress-title">
          <LoaderCircle className="progress-spinner" size={18} aria-hidden="true" />
          <span><strong>正在搜索航班</strong><small>{latest?.type === "retry_waiting" && countdown ? `当前请求被限频，${countdown} 后自动重试（${latest.attempt}/${latest.max_attempts}）` : latest?.message || "正在准备搜索任务"}</small></span>
        </div>
        <div className="progress-actions"><span>{total ? `${completed} / ${total}` : "准备中"}</span><IconButton icon={expanded ? ChevronUp : ChevronDown} label={expanded ? "折叠详细搜索进展" : "展开详细搜索进展"} selected={expanded} aria-expanded={expanded} onClick={() => setExpanded((current) => !current)} /></div>
      </header>
      <progress max={total || 1} value={completed} />
      {expanded ? <div className="progress-details"><div className="progress-meta">
          <span>已完成 {completed}</span>
          <span>失败 {failures}</span>
          <span>最近阶段 {latest?.type || "idle"}</span>
        </div>
        <ol>
          {events.slice(-8).map((event, index) => (
            <li key={`${event.type}-${index}`}>{event.message || `${event.type} ${event.origin || ""}->${event.destination || ""}`}</li>
          ))}
        </ol></div> : null}
    </section>
  );
}

function useRetryCountdown(retryAt?: string): string | null {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!retryAt) return undefined;
    const timer = globalThis.setInterval(() => setNow(Date.now()), 1000);
    return () => globalThis.clearInterval(timer);
  }, [retryAt]);
  if (!retryAt) return null;
  const seconds = Math.max(0, Math.ceil((new Date(retryAt).getTime() - now) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function ResultsTable(props: {
  rows: RenderedResult[];
  filterOptions: ResultFilterOptions;
  sortKey: SortKey;
  sortDirection: SortDirection;
  filters: HistoryFilters;
  expanded: Record<number, boolean>;
  onSort: (key: SortKey) => void;
  onFiltersChange: (filters: HistoryFilters) => void;
  onToggle: (rank: number) => void;
  onOpenLink: (url: string) => void;
}) {
  const columns: Array<[SortKey, string]> = [
    ["price", "价格"],
    ["airline", "航司"],
    ["departure", "出发时间"],
    ["arrival", "到达时间"],
    ["route", "起降地"],
    ["layover", "停留时长"],
    ["layoverCity", "中转城市"],
  ];
  return (
    <section className="results-table-wrap">
      <table className="results-table">
        <colgroup>
          <col className="col-price" />
          <col className="col-airline" />
          <col className="col-time" />
          <col className="col-time" />
          <col className="col-route" />
          <col className="col-layover" />
          <col className="col-city" />
          <col className="col-links" />
        </colgroup>
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th key={key}>
                <div className="column-tools">
                  <button type="button" onClick={() => props.onSort(key)}>{label}{props.sortKey === key ? (props.sortDirection === "asc" ? <ChevronUp size={13} /> : <ChevronDown size={13} />) : null}</button>
                  <ColumnFilter column={key} filters={props.filters} options={props.filterOptions} onChange={props.onFiltersChange} />
                </div>
              </th>
            ))}
            <th>购买链接</th>
          </tr>
        </thead>
        <tbody>
          {props.rows.length === 0 ? <tr className="empty-results-row"><td colSpan={8}>当前筛选没有匹配结果，可从表头清除筛选。</td></tr> : null}
          {props.rows.map((row) => (
            <Fragment key={row.rank}>
              <tr key={row.rank}>
                <td>¥{row.total_price_cny}</td>
                <td>{airlines(row)}</td>
                <td>{formatTableTime(row.outbound.departure_time)}</td>
                <td>{formatTableTime(row.inbound.arrival_time)}</td>
                <td>{compactRoute(row)}</td>
                <td>{layoverHours(row)}h</td>
                <td title={layoverCities(row)}>{compactLayoverCities(row) || "无"}</td>
                <td className="link-cell">
                  <div className="purchase-actions">
                    <button type="button" className="link-button" title={`去程${row.purchase_links.outbound.label}`} onClick={() => props.onOpenLink(row.purchase_links.outbound.url)}>去程<ExternalLink size={12} /></button>
                    <button type="button" className="link-button" title={`回程${row.purchase_links.inbound.label}`} onClick={() => props.onOpenLink(row.purchase_links.inbound.url)}>回程<ExternalLink size={12} /></button>
                  </div>
                  <button type="button" className="detail-toggle" aria-label={props.expanded[row.rank] ? "收起航班详情" : "展开航班详情"} title={props.expanded[row.rank] ? "收起详情" : "展开详情"} onClick={() => props.onToggle(row.rank)}>{props.expanded[row.rank] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>
                </td>
              </tr>
              {props.expanded[row.rank] ? (
                <tr className="detail-row">
                  <td colSpan={8}>
                    <div className="detail-grid">
                      <Leg title="去程" leg={row.outbound} />
                      <Leg title="回程" leg={row.inbound} />
                    </div>
                  </td>
                </tr>
              ) : null}
            </Fragment>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ColumnFilter({ column, filters, options, onChange }: { column: SortKey; filters: HistoryFilters; options: ResultFilterOptions; onChange: (filters: HistoryFilters) => void }) {
  const active = isColumnFilterActive(column, filters);
  const toggle = (key: "include_airlines" | "exclude_airlines" | "airport_routes" | "exclude_layover_airports", value: string) => {
    const selected = new Set(filters[key]);
    selected.has(value) ? selected.delete(value) : selected.add(value);
    onChange({ ...filters, [key]: Array.from(selected) });
  };
  return (
    <details name="result-column-filter" className={`filter-menu column-filter ${active ? "active" : ""}`}>
      <summary aria-label={`${columnLabel(column)}筛选${active ? "，已启用" : ""}`} title={`${columnLabel(column)}筛选`}><SlidersHorizontal size={13} aria-hidden="true" /></summary>
      <div className="column-filter-panel">
        {column === "price" ? <label className="compact-filter-field"><span>最高总价</span><input type="number" min="0" placeholder="不限" value={filters.max_total_price ?? ""} onChange={(event) => onChange({ ...filters, max_total_price: event.target.value ? Number(event.target.value) : null })} /></label> : null}
        {column === "airline" ? <><FilterChecklist title="包含航司" options={options.airlines} selected={filters.include_airlines} onToggle={(value) => toggle("include_airlines", value)} /><FilterChecklist title="排除航司" options={options.airlines} selected={filters.exclude_airlines} onToggle={(value) => toggle("exclude_airlines", value)} /></> : null}
        {column === "departure" ? <TimeRangeFilter title="去程出发时段" value={filters.departure_time_range} onChange={(value) => onChange({ ...filters, departure_time_range: value })} /> : null}
        {column === "arrival" ? <TimeRangeFilter title="回程到达时段" value={filters.arrival_time_range} onChange={(value) => onChange({ ...filters, arrival_time_range: value })} /> : null}
        {column === "route" ? <FilterChecklist title="机场组合" options={options.airport_routes} selected={filters.airport_routes} onToggle={(value) => toggle("airport_routes", value)} /> : null}
        {column === "layover" ? <><label className="compact-filter-field"><span>最大单次停留（小时）</span><input type="number" min="0" step="0.5" placeholder="不限" value={filters.max_single_layover_hours ?? ""} onChange={(event) => onChange({ ...filters, max_single_layover_hours: event.target.value ? Number(event.target.value) : null })} /></label><label className="compact-filter-field"><span>每程最多中转</span><select value={filters.max_stops_per_leg ?? ""} onChange={(event) => onChange({ ...filters, max_stops_per_leg: event.target.value === "" ? null : Number(event.target.value) })}><option value="">不限</option><option value="0">直飞</option><option value="1">1 次</option><option value="2">2 次</option><option value="3">3 次</option></select></label></> : null}
        {column === "layoverCity" ? <FilterChecklist title="排除中转机场" options={options.layover_airports} selected={filters.exclude_layover_airports} onToggle={(value) => toggle("exclude_layover_airports", value)} /> : null}
        {active ? <button type="button" className="clear-column-filter" onClick={() => onChange(clearColumnFilter(column, filters))}>清除此列筛选</button> : null}
      </div>
    </details>
  );
}

function FilterChecklist({ title, options, selected, onToggle }: { title: string; options: string[]; selected: string[]; onToggle: (value: string) => void }) {
  return <fieldset className="filter-checklist"><legend>{title}</legend>{options.length ? options.map((value) => <label key={`${title}-${value}`}><input type="checkbox" checked={selected.includes(value)} onChange={() => onToggle(value)} /><span>{value}</span></label>) : <span className="empty-filter">暂无选项</span>}</fieldset>;
}

function TimeRangeFilter({ title, value, onChange }: { title: string; value: { start: string; end: string } | null; onChange: (value: { start: string; end: string } | null) => void }) {
  const update = (key: "start" | "end", next: string) => {
    const range = { start: value?.start ?? "", end: value?.end ?? "", [key]: next };
    onChange(range.start || range.end ? range : null);
  };
  return <fieldset className="time-range-filter"><legend>{title}</legend><label><span>从</span><input type="time" value={value?.start ?? ""} onChange={(event) => update("start", event.target.value)} /></label><label><span>至</span><input type="time" value={value?.end ?? ""} onChange={(event) => update("end", event.target.value)} /></label></fieldset>;
}

function Leg({ title, leg }: { title: string; leg: RenderedResult["outbound"] }) {
  return <section className="leg"><div className="leg-heading"><h2>{title}</h2><span>¥{leg.price_cny}</span></div><p className="itinerary">{leg.itinerary}</p><div className="segment-grid">{leg.segments.map((segment) => <SegmentRow key={`${title}-${segment.flight_number}-${segment.departure_time}`} segment={segment} />)}</div><div className="layover">{leg.stop_layover_summary}</div></section>;
}

function SegmentRow({ segment }: { segment: FlightSegment }) {
  return <div className="segment-row"><div><strong>{segment.flight_number}</strong><span>{segment.airline_zh || segment.airline}</span></div><div>{segment.aircraft_zh || segment.aircraft || "未知机型"}</div><div>{segment.origin_airport} {formatTime(segment.departure_time)}</div><div>{segment.destination_airport} {formatTime(segment.arrival_time)}</div></div>;
}

function MessageList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return <ul className="message-list">{items.map((item) => <li key={item}>{item}</li>)}</ul>;
}

function JsonDetails({ envelope }: { envelope: GuiSearchEnvelope }) {
  return <details className="json-details"><summary>JSON 详情</summary><pre>{JSON.stringify(envelope, null, 2)}</pre></details>;
}

function sortAndFilter(rows: RenderedResult[], sortKey: SortKey, direction: SortDirection, filters: HistoryFilters): RenderedResult[] {
  const filtered = rows.filter((row) => matchesResultFilters(row, filters));
  return filtered.sort((a, b) => compareRows(a, b, sortKey) * (direction === "asc" ? 1 : -1));
}

export function buildResultFilterOptions(rows: RenderedResult[]): ResultFilterOptions {
  return {
    airlines: Array.from(new Set(rows.flatMap((row) => [...row.outbound.airlines, ...row.inbound.airlines]))).sort((a, b) => a.localeCompare(b, "zh-Hans-CN")),
    airport_routes: Array.from(new Set(rows.map(compactRoute))).sort((a, b) => a.localeCompare(b, "zh-Hans-CN")),
    layover_airports: Array.from(new Set(rows.flatMap(rowLayoverAirports))).sort((a, b) => a.localeCompare(b, "zh-Hans-CN")),
  };
}

export function matchesResultFilters(row: RenderedResult, filters: HistoryFilters): boolean {
  const rowAirlines = new Set([...row.outbound.airlines, ...row.inbound.airlines]);
  if (filters.max_total_price != null && row.total_price_cny > filters.max_total_price) return false;
  if (filters.include_airlines.length && !filters.include_airlines.some((value) => rowAirlines.has(value))) return false;
  if (filters.exclude_airlines.some((value) => rowAirlines.has(value))) return false;
  if (filters.airport_routes.length && !filters.airport_routes.includes(compactRoute(row))) return false;
  if (filters.max_stops_per_leg != null && [row.outbound, row.inbound].some((leg) => leg.stop_count > filters.max_stops_per_leg!)) return false;
  if (filters.max_single_layover_hours != null && [row.outbound, row.inbound].some((leg) => leg.layovers.some((item) => item.duration_hours > filters.max_single_layover_hours!))) return false;
  if (filters.exclude_layover_airports.some((value) => rowLayoverAirports(row).includes(value))) return false;
  if (!timeMatches(row.outbound.departure_time, filters.departure_time_range)) return false;
  if (!timeMatches(row.inbound.arrival_time, filters.arrival_time_range)) return false;
  return true;
}

function rowLayoverAirports(row: RenderedResult): string[] {
  return Array.from(new Set([...row.outbound.layovers, ...row.inbound.layovers].map((item) => item.airport).filter(Boolean)));
}

export function timeMatches(value: string | null, range: { start: string; end: string } | null): boolean {
  if (!range) return true;
  const clock = value?.slice(11, 16) ?? "";
  const start = range.start || "00:00";
  const end = range.end || "23:59";
  return start <= end ? clock >= start && clock <= end : clock >= start || clock <= end;
}

function columnLabel(column: SortKey): string {
  return { price: "价格", airline: "航司", departure: "出发时间", arrival: "到达时间", route: "起降地", layover: "停留时长", layoverCity: "中转城市" }[column];
}

function isColumnFilterActive(column: SortKey, filters: HistoryFilters): boolean {
  if (column === "price") return filters.max_total_price != null;
  if (column === "airline") return filters.include_airlines.length > 0 || filters.exclude_airlines.length > 0;
  if (column === "departure") return filters.departure_time_range != null;
  if (column === "arrival") return filters.arrival_time_range != null;
  if (column === "route") return filters.airport_routes.length > 0;
  if (column === "layover") return filters.max_single_layover_hours != null || filters.max_stops_per_leg != null;
  return filters.exclude_layover_airports.length > 0;
}

function clearColumnFilter(column: SortKey, filters: HistoryFilters): HistoryFilters {
  if (column === "price") return { ...filters, max_total_price: null };
  if (column === "airline") return { ...filters, include_airlines: [], exclude_airlines: [] };
  if (column === "departure") return { ...filters, departure_time_range: null };
  if (column === "arrival") return { ...filters, arrival_time_range: null };
  if (column === "route") return { ...filters, airport_routes: [] };
  if (column === "layover") return { ...filters, max_single_layover_hours: null, max_stops_per_leg: null };
  return { ...filters, exclude_layover_airports: [] };
}

function compareRows(a: RenderedResult, b: RenderedResult, key: SortKey): number {
  if (key === "price") return a.total_price_cny - b.total_price_cny;
  if (key === "departure") return Date.parse(a.outbound.departure_time || "") - Date.parse(b.outbound.departure_time || "");
  if (key === "arrival") return Date.parse(a.inbound.arrival_time || "") - Date.parse(b.inbound.arrival_time || "");
  if (key === "layover") return layoverHours(a) - layoverHours(b);
  const values = { airline: airlines, route, layoverCity: layoverCities } as const;
  return values[key as keyof typeof values](a).localeCompare(values[key as keyof typeof values](b), "zh-Hans-CN");
}

function statusMessages(envelope: GuiSearchEnvelope | null): string[] {
  if (!envelope) return [];
  return Array.from(new Set([envelope.error?.message, envelope.provider_status.message, ...envelope.provider_status.warnings, ...(envelope.response?.warnings ?? [])].filter((item): item is string => Boolean(item))));
}

function networkLabel(envelope: GuiSearchEnvelope | null): string {
  if (!envelope?.network_status) return "unknown";
  if (envelope.provider_status.status === "ok" && envelope.network_status.status === "error") return "预检异常，搜索可用";
  return envelope.network_status.status;
}

function airlines(row: RenderedResult): string {
  return Array.from(new Set([...row.outbound.airlines, ...row.inbound.airlines])).join(" / ");
}

function route(row: RenderedResult): string {
  return `${row.outbound.origin_airport}->${row.outbound.destination_airport} / ${row.inbound.origin_airport}->${row.inbound.destination_airport}`;
}

function compactRoute(row: RenderedResult): string {
  return `${row.outbound.origin_airport}→${row.outbound.destination_airport} / ${row.inbound.origin_airport}→${row.inbound.destination_airport}`;
}

function layoverHours(row: RenderedResult): number {
  return Number((row.outbound.layover_hours_total + row.inbound.layover_hours_total).toFixed(1));
}

function layoverCities(row: RenderedResult): string {
  return Array.from(new Set([...row.outbound.layover_cities, ...row.inbound.layover_cities])).join(" / ");
}

function compactLayoverCities(row: RenderedResult): string {
  return Array.from(new Set([...row.outbound.layover_cities, ...row.inbound.layover_cities]))
    .map((city) => city.match(/^[A-Z]{3}/)?.[0] || city.split("(")[0])
    .join(" / ");
}

function formatTime(value?: string | null): string {
  return value ? value.replace("T", " ").slice(0, 16) : "-";
}

function formatTableTime(value?: string | null): string {
  const formatted = formatTime(value);
  return formatted === "-" ? formatted : formatted.slice(5);
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  try {
    return JSON.stringify(error);
  } catch {
    return "操作失败";
  }
}

export default App;
