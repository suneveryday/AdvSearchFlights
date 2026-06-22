import type { GuiSearchPayload, SearchFormState } from "./types";

export const defaultSearchForm: SearchFormState = {
  origin: "",
  destinationsText: "",
  departure: "",
  returnDate: "",
  provider: "fli",
  maxStops: 1,
  maxLayoverHours: 10,
  adults: 1,
  currency: "CNY",
  cabinClass: "ECONOMY",
  limit: 50,
  httpProxy: "",
  allProxy: "",
  fliTimeoutSeconds: 45,
  guiTimeoutSeconds: 1200,
  maxConcurrentSearches: 1,
};

const MULTI_WORD_LOCATIONS = [
  "Ho Chi Minh City",
  "Dar es Salaam",
  "Rio de Janeiro",
  "Abu Dhabi",
  "Addis Ababa",
  "Buenos Aires",
  "Cape Town",
  "Chiang Mai",
  "Hong Kong",
  "Kota Kinabalu",
  "Kuala Lumpur",
  "Las Vegas",
  "Los Angeles",
  "New York",
  "Phnom Penh",
  "Port Moresby",
  "Saint Petersburg",
  "San Francisco",
  "Siem Reap",
  "São Paulo",
  "Tel Aviv",
].map((location) => location.toUpperCase().split(" "));

export function destinationsFromText(value: string): string[] {
  return value
    .split(/[,，;；/／\n]+/)
    .flatMap(splitLocationChunk)
    .filter(Boolean)
    .filter((item, index, array) => array.findIndex((candidate) => candidate.toUpperCase() === item.toUpperCase()) === index);
}

function splitLocationChunk(value: string): string[] {
  const words = value.trim().split(/\s+/).filter(Boolean);
  const locations: string[] = [];
  for (let index = 0; index < words.length;) {
    const match = MULTI_WORD_LOCATIONS.find((candidate) =>
      candidate.every((word, offset) => words[index + offset]?.toUpperCase() === word),
    );
    if (match) {
      locations.push(words.slice(index, index + match.length).join(" "));
      index += match.length;
    } else {
      locations.push(words[index]);
      index += 1;
    }
  }
  return locations;
}

export function buildGuiSearchPayload(form: SearchFormState): GuiSearchPayload {
  const httpProxy = form.httpProxy.trim();
  const allProxy = form.allProxy.trim();
  const proxy = {
    ...(httpProxy ? {
      http_proxy: httpProxy,
      https_proxy: httpProxy,
      HTTP_PROXY: httpProxy,
      HTTPS_PROXY: httpProxy,
    } : {}),
    ...(allProxy ? {
      all_proxy: allProxy,
      ALL_PROXY: allProxy,
    } : {}),
  };
  const payload: GuiSearchPayload = {
    origin: form.origin.trim(),
    destinations: destinationsFromText(form.destinationsText),
    departure: form.departure,
    return_date: form.returnDate,
    provider: form.provider,
    format: "json",
    max_stops: Number(form.maxStops),
    max_layover_hours: Number(form.maxLayoverHours),
    adults: Number(form.adults),
    currency: form.currency.trim().toUpperCase(),
    cabin_class: form.cabinClass,
    limit: Number(form.limit) === 0 ? null : Number(form.limit),
    no_cooldown: false,
    cooldown_seconds: 2,
    retry_waits: [3, 8, 15],
    request_interval_min_seconds: 3,
    request_interval_max_seconds: 8,
    fli_timeout_seconds: Number(form.fliTimeoutSeconds),
    gui_timeout_seconds: Number(form.guiTimeoutSeconds),
    max_concurrent_searches: Number(form.maxConcurrentSearches),
  };
  if (Object.keys(proxy).length > 0) {
    payload.proxy = proxy;
  }
  return payload;
}

export function validatePayload(payload: GuiSearchPayload): string[] {
  const errors: string[] = [];
  if (!payload.origin) errors.push("请输入出发城市或机场");
  if (payload.destinations.length === 0) errors.push("至少输入 1 个目的地");
  if (payload.destinations.length > 5) errors.push("最多支持 5 个候选目的地");
  if (!payload.departure) errors.push("请选择去程日期");
  if (!payload.return_date) errors.push("请选择回程日期");
  if (payload.limit !== null && payload.limit < 1) errors.push("结果数量必须为 0 或正整数");
  if (payload.fli_timeout_seconds < 5) errors.push("单段查询超时至少为 5 秒");
  if (payload.gui_timeout_seconds < payload.fli_timeout_seconds) errors.push("整次搜索超时不能小于单段查询超时");
  if (payload.max_concurrent_searches < 1) errors.push("并发查询数至少为 1");
  return errors;
}
