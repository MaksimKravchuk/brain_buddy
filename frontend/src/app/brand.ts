// Which visual system the app renders: today's look ("legacy") or Carry On.
//
// Migrated components use role tokens (src/styles/carryOn.css) whose values
// switch on `<html data-brand="carry-on">`, so the whole app changes at once and
// the two systems never mix on one screen. The build default comes from
// `VITE_BRAND`; `?brand=carry-on` or `?brand=legacy` overrides it for this
// browser so the new look can be previewed before the switch.

export type Brand = "legacy" | "carry-on";

export const BRAND_STORAGE_KEY = "bb.brand";
const BRAND_QUERY_PARAM = "brand";

function parseBrand(value: string | null | undefined): Brand | null {
  return value === "carry-on" || value === "legacy" ? value : null;
}

function readStoredBrand(storage: Storage | undefined): Brand | null {
  try {
    return parseBrand(storage?.getItem(BRAND_STORAGE_KEY));
  } catch {
    return null;
  }
}

function storeBrand(storage: Storage | undefined, brand: Brand): void {
  try {
    storage?.setItem(BRAND_STORAGE_KEY, brand);
  } catch {
    // Storage can be blocked (private mode); the override then lasts one page load.
  }
}

export interface ResolveBrandInput {
  buildDefault: string | undefined;
  search: string;
  storage: Storage | undefined;
}

export function resolveBrand({ buildDefault, search, storage }: ResolveBrandInput): Brand {
  const requested = parseBrand(new URLSearchParams(search).get(BRAND_QUERY_PARAM));
  if (requested) {
    storeBrand(storage, requested);
    return requested;
  }
  return readStoredBrand(storage) ?? parseBrand(buildDefault) ?? "legacy";
}

export function applyBrand(root: HTMLElement, brand: Brand): void {
  if (brand === "carry-on") {
    root.dataset.brand = brand;
  } else {
    delete root.dataset.brand;
  }
}

function browserStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function initBrand(): Brand {
  const brand = resolveBrand({
    buildDefault: import.meta.env.VITE_BRAND as string | undefined,
    search: window.location.search,
    storage: browserStorage()
  });
  applyBrand(document.documentElement, brand);
  return brand;
}
