/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Powered backend runs in a sibling service; allow the env-injected URL.
  experimental: {},
};

export default nextConfig;
