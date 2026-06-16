/**
 * Build-time data loaders. These files are read once during astro build and
 * passed into getStaticPaths / component props. They never ship to the
 * browser — Pagefind handles all runtime data.
 */
import artists from "../data/artists.json";
import artistsFull from "../data/artists_full.json";
import classifications from "../data/classifications.json";
import decades from "../data/decades.json";
import meta from "../data/meta.json";

export interface ArtistRef {
  id: string;
  name: string;
  sort_name: string | null;
  begin_date: string | null;
  end_date: string | null;
}

export interface ImageRef {
  id: number;
  url: string;
}

export interface ExhibitionRef {
  id: string;
  title: string;
  start_date: string | null;
  end_date: string | null;
  year: number | null;
}

export interface Artwork {
  id: string;
  title: string | null;
  display_artist_text: string | null;
  display_date: string | null;
  classification: string | null;
  medium: string | null;
  dimensions: string | null;
  accession_number: string | null;
  acquisition_year: number | null;
  credit_line: string | null;
  credit_line_repro: string | null;
  description: string | null;
  alt_text: string | null;
  ai_alt_text: string | null;
  visual_description: string | null;
  on_view: boolean | null;
  is_portfolio: boolean | null;
  is_virtual: boolean | null;
  department: string | null;
  edition: string | null;
  publication_info: string | null;
  artists: ArtistRef[];
  images: ImageRef[];
  primary_image_url: string | null;
  exhibitions: ExhibitionRef[];
}

export interface Artist {
  id: string;
  display_name: string;
  sort_name: string | null;
  begin_date: string | null;
  end_date: string | null;
  n_works: number;
}

export interface Classification {
  classification: string;
  n: number;
}

export interface Decade {
  decade: number;
  n: number;
}

export interface ArtistWork {
  id: string;
  title: string | null;
  display_date: string | null;
  classification: string | null;
  acquisition_year: number | null;
  primary_image_url: string | null;
  display_artist_text: string | null;
  ai_alt_text: string | null;
  alt_text: string | null;
}

export interface ArtistExhibition {
  id: string;
  title: string;
  start_date: string | null;
  end_date: string | null;
  year: number | null;
}

export interface ArtistFull {
  id: string;
  display_name: string;
  sort_name: string | null;
  display_date: string | null;
  begin_date: string | null;
  end_date: string | null;
  biography: string | null;
  on_view: boolean | null;
  artport: boolean | null;
  biennial: boolean | null;
  in_collection: boolean | null;
  ulan_id: string | null;
  wikidata_id: string | null;
  is_temp_id: boolean;
  works: ArtistWork[];
  exhibitions: ArtistExhibition[];
  n_works: number;
  n_exhibitions: number;
}

export interface Meta {
  generated_at: string;
  warehouse_path: string;
  warehouse_sha256: string;
  counts: {
    artworks: number;
    artists_with_works: number;
    artists_total: number;
  };
}

const catalogShards = import.meta.glob<{ default: Artwork[] }>(
  "../data/catalog_*.json",
  { eager: true },
);
export const ARTWORKS: Artwork[] = Object.keys(catalogShards)
  .sort()
  .flatMap((k) => catalogShards[k].default);
export const ARTISTS = artists as unknown as Artist[];
export const ARTISTS_FULL = artistsFull as unknown as ArtistFull[];
export const CLASSIFICATIONS = classifications as unknown as Classification[];
export const DECADES = decades as unknown as Decade[];
export const META = meta as unknown as Meta;

export const ARTWORKS_BY_ID = new Map<string, Artwork>(
  ARTWORKS.map((a) => [a.id, a]),
);

export function smallImageVariant(url: string | null): string | null {
  if (!url) return null;
  const parts = url.split("/");
  const fname = parts.at(-1)!;
  const stripped = fname.replace(/^(small|medium|large)_/, "");
  parts[parts.length - 1] = "small_" + stripped;
  return parts.join("/");
}

export function sortForBrowse(a: Artwork, b: Artwork): number {
  const ya = a.acquisition_year ?? -1;
  const yb = b.acquisition_year ?? -1;
  if (yb !== ya) return yb - ya;
  return b.id.localeCompare(a.id);
}

/** Plain text excerpt suitable for Pagefind body indexing. Strips HTML. */
export function stripHtml(s: string | null | undefined): string {
  if (!s) return "";
  return s
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Up to N other works by the same artist (any of them), excluding self. */
export function relatedWorks(a: Artwork, n = 8): Artwork[] {
  const artistIds = new Set(a.artists.map((x) => x.id));
  if (artistIds.size === 0) return [];
  const out: Artwork[] = [];
  for (const candidate of ARTWORKS) {
    if (candidate.id === a.id) continue;
    if (candidate.artists.some((x) => artistIds.has(x.id))) {
      out.push(candidate);
      if (out.length >= n) break;
    }
  }
  return out;
}
