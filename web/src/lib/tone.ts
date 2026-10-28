import { posterUrl } from '../api/flicks';
import { hue } from './format';

const SIZE = 12;
const tones = new Map<string, Promise<string>>();

/** A dark, room-light version of an RGB colour: same hue, a little more saturated, low lightness. */
function roomLight(r: number, g: number, b: number): string {
  const max = Math.max(r, g, b) / 255;
  const min = Math.min(r, g, b) / 255;
  const l = (max + min) / 2;
  const d = max - min;
  let h = 0;
  if (d > 0) {
    const [rn, gn, bn] = [r / 255, g / 255, b / 255];
    if (max === rn) h = ((gn - bn) / d) % 6;
    else if (max === gn) h = (bn - rn) / d + 2;
    else h = (rn - gn) / d + 4;
    h = Math.round(h * 60 + 360) % 360;
  }
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  // Posters are often pale; push the colour so the room clearly takes it on, but keep it dark.
  return `hsl(${h} ${Math.round(Math.min(0.75, s * 1.6 + 0.15) * 100)}% ${Math.round(Math.min(0.22, 0.13 + l * 0.1) * 100)}%)`;
}

/**
 * The colour a poster throws into a dark room, for the page's ambient light: its average colour, weighted
 * toward saturated pixels (a white poster with a red title reads red), kept dark. Posters come from this
 * server, so the canvas can read them. Titles without a poster get a colour from their ID.
 */
export function posterTone(id: string, hasPoster: boolean): Promise<string> {
  const fallback = `hsl(${hue(id)} 40% 14%)`;
  if (!hasPoster) return Promise.resolve(fallback);
  let tone = tones.get(id);
  if (!tone) {
    tone = new Promise<string>(resolve => {
      const image = new Image();
      image.decoding = 'async';
      image.onerror = () => resolve(fallback);
      image.onload = () => {
        try {
          const canvas = document.createElement('canvas');
          canvas.width = canvas.height = SIZE;
          const context = canvas.getContext('2d', { willReadFrequently: true });
          if (!context) return resolve(fallback);
          context.drawImage(image, 0, 0, SIZE, SIZE);
          const pixels = context.getImageData(0, 0, SIZE, SIZE).data;
          let r = 0;
          let g = 0;
          let b = 0;
          let total = 0;
          for (let i = 0; i < pixels.length; i += 4) {
            const [pr, pg, pb] = [pixels[i] ?? 0, pixels[i + 1] ?? 0, pixels[i + 2] ?? 0];
            const weight = 0.15 + (Math.max(pr, pg, pb) - Math.min(pr, pg, pb)) / 255;
            r += pr * weight;
            g += pg * weight;
            b += pb * weight;
            total += weight;
          }
          resolve(roomLight(r / total, g / total, b / total));
        } catch {
          resolve(fallback);
        }
      };
      image.src = posterUrl(id);
    });
    tones.set(id, tone);
  }
  return tone;
}
