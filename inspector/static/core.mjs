export const COLORS = {H: '#f48780', A: '#7dd5c9', D: '#b2a5d6', X: '#5e6b74'};
export const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
export function frameFromTime(seconds, fps, frames) {
  return clamp(Math.floor(seconds * fps + 1e-6), 0, frames - 1);
}
export function timecode(frame, fps) {
  const millis = Math.round(frame / fps * 1000);
  const mins = Math.floor(millis / 60000);
  return `${String(mins).padStart(2, '0')}:${String(Math.floor(millis / 1000) % 60).padStart(2, '0')}.${String(millis % 1000).padStart(3, '0')}`;
}
export function segmentAt(segments, frame) {
  let low = 0, high = segments.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1, item = segments[mid];
    if (frame < item.start) high = mid - 1;
    else if (frame >= item.end) low = mid + 1;
    else return item;
  }
  return null;
}
export function transition(segments, frame, direction) {
  let low = 0, high = segments.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (segments[mid].start < frame || (direction > 0 && segments[mid].start === frame)) low = mid + 1;
    else high = mid;
  }
  return segments[direction > 0 ? low : low - 1]?.start ?? null;
}
// One bin per CSS pixel; mixed bins disclose boundaries hidden at this zoom.
export function timelineBins(segments, start, end, width) {
  const pixels = Math.max(1, Math.ceil(width)), result = [];
  for (let pixel = 0; pixel < pixels; pixel++) {
    const first = start + pixel / pixels * (end - start);
    const stop = start + (pixel + 1) / pixels * (end - start);
    const item = segmentAt(segments, first);
    if (!item) continue;
    const mixed = item.end < stop;
    const label = mixed ? null : item.label, previous = result.at(-1);
    if (previous && previous.x + previous.width === pixel && previous.mixed === mixed && previous.label === label) previous.width++;
    else result.push({x:pixel,width:1,label,mixed});
  }
  return result.map(bin => ({...bin,x:bin.x / pixels * width,width:bin.width / pixels * width}));
}
export function project(matrix, x, y) {
  if (!matrix || matrix.length !== 9 || !matrix.every(Number.isFinite)) return null;
  const rows = [matrix.slice(0, 3), matrix.slice(3, 6), matrix.slice(6, 9)];
  const scales = rows.map(row => Math.max(...row.map(Math.abs)));
  if (scales.some(scale => scale === 0)) return null;
  const [a,b,c,d,e,f,g,h,i] = rows.flatMap((row, index) => row.map(value => value / scales[index]));
  const terms = [a*e*i,b*f*g,c*d*h,-c*e*g,-b*d*i,-a*f*h];
  if (Math.abs(terms.reduce((sum, value) => sum + value, 0)) <=
      32 * Number.EPSILON * terms.reduce((sum, value) => sum + Math.abs(value), 0)) return null;
  const scale = Math.max(...matrix.map(Math.abs));
  matrix = matrix.map(value => value / scale);
  const divisor = matrix[6] * x + matrix[7] * y + matrix[8];
  const denominatorScale = Math.abs(matrix[6] * x) + Math.abs(matrix[7] * y) + Math.abs(matrix[8]);
  if (Math.abs(divisor) <= Number.EPSILON * 32 * denominatorScale) return null;
  const result = [(matrix[0] * x + matrix[1] * y + matrix[2]) / divisor,
                  (matrix[3] * x + matrix[4] * y + matrix[5]) / divisor];
  return result.every(Number.isFinite) ? result : null;
}
export function nearestPlayer(players, ball, pitch) {
  if (!ball) return null;
  let closest = null;
  for (const player of players) {
    const distance = Math.hypot((player.x - ball.x) * pitch.length, (player.y - ball.y) * pitch.width);
    if (!closest || distance < closest.distance) closest = {...player, distance};
  }
  return closest;
}
export function timelineWindow(frame, seconds, fps, frames) {
  if (!seconds || seconds * fps >= frames) return [0, frames];
  const length = Math.max(1, Math.round(seconds * fps));
  const start = clamp(Math.round(frame - length / 2), 0, frames - length);
  return [start, start + length];
}
export function timelineFrame(x, left, width, start, end) {
  return clamp(Math.floor(start + (x - left) / width * (end - start)), start, end - 1);
}
