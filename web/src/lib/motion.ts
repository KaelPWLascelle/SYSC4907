/** The viewer asked their system for less motion: no autoplay, no smooth scrolling, no countdowns. */
export const prefersReducedMotion = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
