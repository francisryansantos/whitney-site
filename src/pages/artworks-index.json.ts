import {
  ARTWORKS,
  sortForBrowse,
  type Artwork,
} from "../lib/catalog";

export interface BrowseArtwork {
  id: string;
  url: string;
  title: string | null;
  artist: string | null;
  date: string | null;
  classification: string | null;
  image: string | null;
  thumb: string | null;
  artistIds: string[];
  visualText: string;
}

function toBrowseArtwork(artwork: Artwork): BrowseArtwork {
  return {
    id: artwork.id,
    url: `/artworks/${artwork.id}`,
    title: artwork.title,
    artist: artwork.display_artist_text || artwork.artists[0]?.name || null,
    date: artwork.display_date,
    classification: artwork.classification,
    image: artwork.primary_image_url,
    thumb: artwork.primary_image_url,
    artistIds: artwork.artists.map((artist) => artist.id),
    visualText: [
      artwork.ai_alt_text,
      artwork.alt_text,
      artwork.visual_description,
      artwork.description,
      artwork.medium,
      artwork.classification,
    ].filter(Boolean).join(" "),
  };
}

export function GET() {
  const body = JSON.stringify(
    [...ARTWORKS]
      .filter((artwork) => artwork.primary_image_url)
      .sort(sortForBrowse)
      .map(toBrowseArtwork),
  );

  return new Response(body, {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
