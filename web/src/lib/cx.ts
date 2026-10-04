/** Join class names, skipping falsy values. */
export const cx = (...names: (string | false | null | undefined | 0)[]) => names.filter(Boolean).join(' ');
