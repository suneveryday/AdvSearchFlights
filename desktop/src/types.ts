export type ProviderName = "auto" | "mock" | "fli" | "skyscanner";

export interface SearchFormState {
  origin: string;
  destinationsText: string;
  departure: string;
  returnDate: string;
  provider: ProviderName;
  maxStops: number;
  maxLayoverHours: number;
  adults: number;
  currency: string;
  cabinClass: "ECONOMY" | "PREMIUM_ECONOMY" | "BUSINESS" | "FIRST";
  limit: number;
  httpProxy: string;
  allProxy: string;
  fliTimeoutSeconds: number;
  guiTimeoutSeconds: number;
  maxConcurrentSearches: number;
}

export interface GuiSearchPayload {
  origin: string;
  destinations: string[];
  departure: string;
  return_date: string;
  provider: ProviderName;
  format: "json";
  max_stops: number;
  max_layover_hours: number;
  adults: number;
  currency: string;
  cabin_class: "ECONOMY" | "PREMIUM_ECONOMY" | "BUSINESS" | "FIRST";
  limit: number | null;
  no_cooldown: boolean;
  cooldown_seconds: number;
  retry_waits: number[];
  request_interval_min_seconds: number;
  request_interval_max_seconds: number;
  fli_timeout_seconds: number;
  gui_timeout_seconds: number;
  max_concurrent_searches: number;
  proxy?: {
    http_proxy?: string;
    https_proxy?: string;
    HTTP_PROXY?: string;
    HTTPS_PROXY?: string;
    all_proxy?: string;
    ALL_PROXY?: string;
  };
}

export interface FlightSegment {
  route: string;
  flight_number: string;
  airline: string;
  airline_zh?: string | null;
  aircraft?: string | null;
  aircraft_zh?: string | null;
  origin_airport: string;
  origin_airport_name_zh?: string | null;
  departure_time: string;
  destination_airport: string;
  destination_airport_name_zh?: string | null;
  arrival_time: string;
}

export interface OneWayRendered {
  itinerary: string;
  segments: FlightSegment[];
  segment_summaries: string[];
  stop_count: number;
  layovers: Array<{ airport: string; airport_name_zh?: string | null; duration_hours: number }>;
  stop_layover_summary: string;
  price_cny: number;
  airlines: string[];
  departure_time: string | null;
  arrival_time: string | null;
  origin_airport: string;
  destination_airport: string;
  layover_hours_total: number;
  layover_cities: string[];
}

export interface PurchaseLink {
  type: "booking" | "search";
  label: string;
  url: string;
}

export interface RenderedResult {
  rank: number;
  total_price_cny: number;
  outbound: OneWayRendered;
  inbound: OneWayRendered;
  purchase_links: {
    outbound: PurchaseLink;
    inbound: PurchaseLink;
  };
}

export interface GuiSearchEnvelope {
  ok: boolean;
  response: {
    result_count: number;
    rendered: RenderedResult[];
    warnings: string[];
  } | null;
  network_status: {
    status: string;
    proxy: { has_proxy: boolean; http_proxy?: string | null; https_proxy?: string | null; all_proxy?: string | null };
    checks: Array<{ name: string; status: string; ok: boolean | null; message: string; latency_ms?: number | null }>;
  } | null;
  provider_status: {
    provider: string;
    status: string;
    result_count: number;
    warnings: string[];
    categories: string[];
    message?: string | null;
  };
  error: { type: string; message: string } | null;
  history_batch_id?: string | null;
}

export interface HistoryBatch {
  id: string;
  created_at: string;
  provider: string;
  origin: string;
  destinations: string[];
  departure: string;
  return_date: string;
  cabin_class: string;
  result_count: number;
  minimum_price_cny?: number | null;
  label: string;
}

export interface HistoryDetail extends HistoryBatch {
  query: Record<string, unknown>;
  rendered: RenderedResult[];
}

export interface HistoryGroup {
  id: string;
  origin: string;
  destinations: string[];
  departure: string;
  return_date: string;
  cabin_class: string;
  adults: number;
  max_stops: number;
  max_layover_hours: number;
  provider: string;
  currency: string;
  created_at: string;
  updated_at: string;
  batch_count?: number;
  result_count?: number;
  latest_created_at?: string;
  title: string;
  date_label: string;
  schedule_enabled?: number | boolean;
  schedule_enabled_at?: string | null;
  schedule_next_run_at?: string | null;
  schedule_last_run_at?: string | null;
  schedule_status?: ScheduleStatus | null;
  schedule_last_error?: string | null;
  schedule_interval_hours?: number | null;
  schedule_notification_enabled?: number | boolean | null;
  schedule_price_threshold?: number | null;
  schedule_desktop_last_notified_price?: number | null;
  schedule_reminder_last_notified_price?: number | null;
}

export type ScheduleStatus = "disabled" | "scheduled" | "queued" | "running" | "rate_limited_wait" | "succeeded" | "failed" | "paused_expired";

export interface HistorySchedule {
  group_id: string;
  enabled: boolean;
  enabled_at: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  status: ScheduleStatus;
  last_error: string | null;
  interval_hours?: number;
  notification_enabled?: boolean;
  price_threshold?: number | null;
  desktop_last_notified_price?: number | null;
  desktop_last_notified_at?: string | null;
  reminder_last_notified_price?: number | null;
  reminder_last_notified_at?: string | null;
  origin: string;
  destinations: string[];
  departure: string;
  return_date: string;
  query?: Record<string, unknown>;
}

export interface AppSettings {
  rate_limit_retry_minutes: number;
  analytics_consent: "unset" | "granted" | "denied";
  analytics_install_id: string;
}

export interface AppSettingsUpdate {
  rate_limit_retry_minutes?: number;
  analytics_consent?: AppSettings["analytics_consent"];
}

export interface AlertPermissionStatus {
  desktop: "granted" | "denied" | "prompt" | "error" | string;
  reminders: "granted" | "denied" | "unchecked" | string;
  reminders_message?: string | null;
}

export interface HistoryGroupDetail extends HistoryGroup {
  batches: HistoryBatch[];
}

export interface HistoryFilters {
  max_total_price: number | null;
  include_airlines: string[];
  exclude_airlines: string[];
  airport_routes: string[];
  max_stops_per_leg: number | null;
  max_single_layover_hours: number | null;
  exclude_layover_airports: string[];
  departure_time_range: { start: string; end: string } | null;
  arrival_time_range: { start: string; end: string } | null;
}

export interface HistoryTrendPoint {
  batch_id: string;
  created_at: string;
  label: string;
  minimum_price_cny: number | null;
  match_count: number;
}

export interface HistoryGroupResults {
  group: HistoryGroup;
  batches: HistoryBatch[];
  selected_batch: HistoryBatch;
  filters: HistoryFilters;
  filter_options: {
    airlines: string[];
    airport_routes: string[];
    layover_airports: string[];
  };
  trend: HistoryTrendPoint[];
  rendered: RenderedResult[];
  result_count: number;
}

export interface SearchProgressEvent {
  type:
    | "client_started"
    | "queued"
    | "process_started"
    | "started"
    | "network_check"
    | "leg_started"
    | "leg_finished"
    | "leg_failed"
    | "rate_limit_detected"
    | "retry_waiting"
    | "retry_started"
    | "retry_exhausted"
    | "provider_retry_waiting"
    | "provider_retry_started"
    | "provider_retry_exhausted"
    | "notification_sent"
    | "notification_failed"
    | "combining"
    | "completed"
    | "failed";
  message?: string;
  provider?: ProviderName | string;
  cli_path?: string;
  completed?: number;
  total?: number;
  origin?: string;
  destination?: string;
  date?: string;
  direction?: string;
  attempt?: number;
  max_attempts?: number;
  retry_at?: string;
  wait_seconds?: number;
  source?: "manual" | "scheduled" | string;
  group_id?: string;
  channel?: "desktop" | "reminders" | string;
  network_status?: GuiSearchEnvelope["network_status"];
  envelope?: GuiSearchEnvelope;
}

export interface NetworkCheckModule {
  name: string;
  label: string;
  status: "ok" | "warning" | "error" | "skipped" | string;
  ok: boolean | null;
  message: string;
  latency_ms?: number | null;
  details?: Record<string, unknown>;
}

export interface NetworkCheckResult {
  status: "ok" | "warning" | "error" | string;
  modules: NetworkCheckModule[];
}
