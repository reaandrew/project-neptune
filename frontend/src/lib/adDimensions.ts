// Creative-brief lookups for the ad generator. Mirror the worker's
// label tables in ads-worker/handler.py so the UI labels and the
// values the worker will actually consume stay in sync.

export const PLATFORMS: Array<[string, string]> = [
  ['facebook-feed', 'Facebook feed'],
  ['instagram-feed', 'Instagram feed'],
  ['instagram-story', 'Instagram story'],
  ['linkedin-post', 'LinkedIn post'],
  ['tiktok-reel', 'TikTok / Reel cover'],
  ['google-display', 'Google display ad'],
  ['website-banner', 'Website banner'],
  ['email-header', 'Email header'],
  ['print-flyer', 'Print flyer'],
  ['multi-platform', 'Multi-platform pack'],
];

export const OBJECTIVES: Array<[string, string]> = [
  ['brand-awareness', 'Brand awareness'],
  ['get-leads', 'Get leads'],
  ['promote-service', 'Promote a service'],
  ['promote-product', 'Promote a product'],
  ['promote-offer', 'Promote an offer'],
  ['drive-traffic', 'Drive website traffic'],
  ['book-appointments', 'Book appointments'],
  ['promote-event', 'Promote an event'],
  ['build-trust', 'Build trust / social proof'],
  ['recruitment', 'Recruitment'],
];

export const LAYOUTS: Array<[string, string]> = [
  ['single-hero', 'Single hero image'],
  ['full-image-overlay', 'Full image with text overlay'],
  ['split-image-text', 'Split image and text'],
  ['grid-collage', 'Grid / collage'],
  ['product-card', 'Product card'],
  ['service-card', 'Service card'],
  ['offer-card', 'Offer card'],
  ['testimonial-card', 'Testimonial card'],
  ['before-after', 'Before-and-after'],
  ['carousel-sequence', 'Carousel sequence'],
];

export const ANGLES: Array<[string, string]> = [
  ['benefit-led', 'Benefit-led'],
  ['problem-solution', 'Problem / solution'],
  ['trust-led', 'Trust-led'],
  ['local-expertise', 'Local expertise'],
  ['offer-led', 'Offer-led'],
  ['seasonal', 'Seasonal'],
  ['educational', 'Educational'],
  ['testimonial-led', 'Testimonial-led'],
  ['premium-quality', 'Premium quality'],
  ['urgency-limited', 'Urgency / limited time'],
];

// Tuple: [id, label, default-on?]
export const ELEMENTS: Array<[string, string, boolean]> = [
  ['logo', 'Logo', true],
  ['headline', 'Headline', true],
  ['subheadline', 'Subheadline', false],
  ['body', 'Body copy', false],
  ['cta', 'CTA button', true],
  ['website', 'Website', true],
  ['phone', 'Phone number', false],
  ['email', 'Email', false],
  ['social', 'Social handle', false],
  ['offer-badge', 'Offer badge', false],
  ['star-rating', 'Star rating', false],
  ['testimonial', 'Testimonial', false],
  ['price', 'Price', false],
  ['qr-code', 'QR code', false],
  ['location', 'Location', false],
  ['legal', 'Legal disclaimer', false],
];

export const DEFAULT_ELEMENT_SET: Set<string> = new Set(
  ELEMENTS.filter(([, , d]) => d).map(([id]) => id),
);
