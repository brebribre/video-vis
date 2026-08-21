<script setup lang="ts">
import { computed } from 'vue'
import type { AspectRatio, PlatformPreview, OverlayVariant } from '../types'
import { SAFE_ZONES, overlayVariantFor } from '../types'

const props = defineProps<{
  platform: PlatformPreview
  aspectRatio: AspectRatio
  showSafeZones: boolean
  username: string
  caption: string
}>()

const variant = computed<OverlayVariant | null>(() =>
  overlayVariantFor(props.platform, props.aspectRatio),
)

const safeStyle = computed(() => {
  if (!variant.value) return {}
  const s = SAFE_ZONES[variant.value]
  return {
    top: s.top * 100 + '%',
    right: s.right * 100 + '%',
    bottom: s.bottom * 100 + '%',
    left: s.left * 100 + '%',
  }
})

// Feed chrome renders outside the media, so there is nothing to shade.
const hasSafeZone = computed(() => variant.value !== null && variant.value !== 'ig-feed')
</script>

<template>
  <div v-if="variant" class="overlay" :class="variant">
    <!-- ============================= TikTok ============================= -->
    <template v-if="variant === 'tiktok'">
      <div class="status-bar">
        <span>9:41</span>
        <span class="status-right">
          <svg class="ic sig" viewBox="0 0 24 24"><path d="M2 18h3v4H2zm5-4h3v8H7zm5-5h3v13h-3zm5-6h3v19h-3z" /></svg>
          <span class="battery" />
        </span>
      </div>

      <div class="tt-tabs">
        <span class="dim">Following</span>
        <span class="active">For You</span>
      </div>

      <div class="rail">
        <div class="rail-item avatar-item">
          <div class="avatar" />
          <div class="follow-badge">+</div>
        </div>
        <div class="rail-item">
          <span class="ic-wrap"><svg class="ic" viewBox="0 0 24 24"><path d="M12 21S3.6 15.5 3.6 9.9A4.6 4.6 0 0 1 12 7.2a4.6 4.6 0 0 1 8.4 2.7C20.4 15.5 12 21 12 21z" /></svg></span>
          <span class="count">328.4K</span>
        </div>
        <div class="rail-item">
          <span class="ic-wrap"><svg class="ic" viewBox="0 0 24 24"><path d="M3 4.5h18v12H8.4L3 21z" /></svg></span>
          <span class="count">1,204</span>
        </div>
        <div class="rail-item">
          <span class="ic-wrap"><svg class="ic" viewBox="0 0 24 24"><path d="M5.5 2.5h13v19L12 16.9 5.5 21.5z" /></svg></span>
          <span class="count">9,881</span>
        </div>
        <div class="rail-item">
          <span class="ic-wrap"><svg class="ic" viewBox="0 0 24 24"><path d="M2.5 19.5c.6-6.2 5-9 9.5-9.2V5.5l9.5 7.6-9.5 7.6v-4.9c-4.4-.2-7.3 1-9.5 3.7z" /></svg></span>
          <span class="count">4,512</span>
        </div>
        <div class="rail-item">
          <div class="disc" />
        </div>
      </div>

      <div class="caption-block">
        <div class="handle">{{ username }}</div>
        <div class="caption">{{ caption }}</div>
        <div class="music">
          <svg class="ic note" viewBox="0 0 24 24"><path d="M9 17.5V5.2l10-2v11" /><circle cx="6.5" cy="17.5" r="2.6" /><circle cx="16.5" cy="14.2" r="2.6" /></svg>
          <span>original sound &middot; {{ username }}</span>
        </div>
      </div>

      <div class="nav">
        <span class="nav-item active">Home</span>
        <span class="nav-item">Shop</span>
        <span class="create">+</span>
        <span class="nav-item">Inbox</span>
        <span class="nav-item">Profile</span>
      </div>
    </template>

    <!-- ========================= Instagram Reels ========================= -->
    <template v-if="variant === 'ig-reels'">
      <div class="status-bar">
        <span>9:41</span>
        <span class="status-right">
          <svg class="ic sig" viewBox="0 0 24 24"><path d="M2 18h3v4H2zm5-4h3v8H7zm5-5h3v13h-3zm5-6h3v19h-3z" /></svg>
          <span class="battery" />
        </span>
      </div>

      <div class="ig-header">
        <span class="ig-title">Reels</span>
        <svg class="ic cam" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <rect x="2.5" y="6.5" width="14" height="11" rx="3" /><path d="M16.5 11l5-3v8l-5-3z" />
        </svg>
      </div>

      <div class="rail">
        <div class="rail-item">
          <span class="ic-wrap"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20.5S3.8 15.2 3.8 9.8A4.4 4.4 0 0 1 12 7.3a4.4 4.4 0 0 1 8.2 2.5c0 5.4-8.2 10.7-8.2 10.7z" /></svg></span>
          <span class="count">92.1K</span>
        </div>
        <div class="rail-item">
          <span class="ic-wrap"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20.5 11.6a8.4 8.4 0 0 1-12.2 7.5L3.5 20.5l1.5-4.6a8.4 8.4 0 1 1 15.5-4.3z" /></svg></span>
          <span class="count">843</span>
        </div>
        <div class="rail-item">
          <span class="ic-wrap"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21.5 2.5 10.8 13.2M21.5 2.5l-6.8 19-3.9-8.3-8.3-3.9z" /></svg></span>
          <span class="count">2,109</span>
        </div>
        <div class="rail-item">
          <span class="ic-wrap dots"><svg class="ic" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.9" /><circle cx="12" cy="12" r="1.9" /><circle cx="19" cy="12" r="1.9" /></svg></span>
        </div>
        <div class="rail-item"><div class="audio-thumb" /></div>
      </div>

      <div class="caption-block">
        <div class="ig-user-row">
          <div class="avatar sm" />
          <span class="handle">{{ username }}</span>
          <span class="follow-pill">Follow</span>
        </div>
        <div class="caption">{{ caption }}</div>
        <div class="music">
          <svg class="ic note" viewBox="0 0 24 24"><path d="M9 17.5V5.2l10-2v11" /><circle cx="6.5" cy="17.5" r="2.6" /><circle cx="16.5" cy="14.2" r="2.6" /></svg>
          <span>{{ username }} &middot; Original audio</span>
        </div>
      </div>

      <div class="nav">
        <span class="nav-item active">Home</span>
        <span class="nav-item">Search</span>
        <span class="nav-item">Create</span>
        <span class="nav-item">Reels</span>
        <span class="avatar xs" />
      </div>
    </template>

    <!-- ========================== Instagram Feed ========================= -->
    <!-- Feed chrome sits outside the 4:5 media, so it is rendered above and
         below the frame rather than on top of it. -->
    <template v-if="variant === 'ig-feed'">
      <div class="feed-header">
        <div class="avatar sm ring" />
        <div class="feed-header-text">
          <span class="handle">{{ username }}</span>
          <span class="sub">Sponsored</span>
        </div>
        <svg class="ic dots-h" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.9" /><circle cx="12" cy="12" r="1.9" /><circle cx="19" cy="12" r="1.9" /></svg>
      </div>

      <div class="feed-footer">
        <div class="feed-actions">
          <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 20.5S3.8 15.2 3.8 9.8A4.4 4.4 0 0 1 12 7.3a4.4 4.4 0 0 1 8.2 2.5c0 5.4-8.2 10.7-8.2 10.7z" /></svg>
          <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M20.5 11.6a8.4 8.4 0 0 1-12.2 7.5L3.5 20.5l1.5-4.6a8.4 8.4 0 1 1 15.5-4.3z" /></svg>
          <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M21.5 2.5 10.8 13.2M21.5 2.5l-6.8 19-3.9-8.3-8.3-3.9z" /></svg>
          <svg class="ic save" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5.5 2.8h13v18.4L12 16.6l-6.5 4.6z" /></svg>
        </div>
        <div class="feed-likes">12,480 likes</div>
        <div class="feed-caption"><span class="handle">{{ username }}</span> {{ caption }}</div>
      </div>
    </template>

    <!-- ============================ Safe zone ============================ -->
    <div v-if="showSafeZones && hasSafeZone" class="safe-layer">
      <div class="safe" :style="safeStyle">
        <span class="safe-label">Safe zone</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: absolute;
  inset: 0;
  /* Sizes below are expressed in cqw so the mock scales with the preview. */
  container-type: inline-size;
  pointer-events: none;
  color: #fff;
  /* .stage sets line-height:0 to kill the inline-block descender gap — undo it here */
  line-height: 1.25;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  text-shadow: 0 0.15cqw 0.6cqw rgba(0, 0, 0, 0.55);
  border-radius: 8px;
}

.overlay :is(svg) {
  fill: currentColor;
}

.ic {
  width: 100%;
  height: 100%;
  display: block;
}

/* ---------- status bar ---------- */
.status-bar {
  position: absolute;
  top: 1.4cqw;
  left: 5cqw;
  right: 5cqw;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 3.3cqw;
  font-weight: 600;
}

.status-right {
  display: flex;
  align-items: center;
  gap: 1.2cqw;
}

.sig {
  width: 3.4cqw;
  height: 3.4cqw;
}

.battery {
  width: 5.4cqw;
  height: 2.6cqw;
  border: 0.28cqw solid rgba(255, 255, 255, 0.8);
  border-radius: 0.8cqw;
  background: linear-gradient(to right, #fff 70%, transparent 70%);
  background-clip: content-box;
  padding: 0.3cqw;
}

/* ---------- TikTok top tabs ---------- */
.tt-tabs {
  position: absolute;
  top: 7cqw;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  gap: 5cqw;
  font-size: 3.7cqw;
  font-weight: 600;
}

.tt-tabs .dim {
  opacity: 0.6;
}

.tt-tabs .active {
  position: relative;
}

.tt-tabs .active::after {
  content: '';
  position: absolute;
  left: 20%;
  right: 20%;
  bottom: -1.4cqw;
  height: 0.5cqw;
  border-radius: 0.5cqw;
  background: #fff;
}

/* ---------- Instagram Reels header ---------- */
.ig-header {
  position: absolute;
  top: 7cqw;
  left: 4cqw;
  right: 4cqw;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ig-title {
  font-size: 5cqw;
  font-weight: 700;
}

.cam {
  width: 6cqw;
  height: 6cqw;
}

/* ---------- right action rail ---------- */
.rail {
  position: absolute;
  right: 2.4cqw;
  bottom: 19cqw;
  width: 13cqw;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3.4cqw;
}

.rail-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.9cqw;
}

.ic-wrap {
  display: block;
  width: 7.4cqw;
  height: 7.4cqw;
  filter: drop-shadow(0 0.2cqw 0.5cqw rgba(0, 0, 0, 0.5));
}

.count {
  font-size: 2.6cqw;
  font-weight: 600;
}

.avatar-item {
  position: relative;
  margin-bottom: 1.6cqw;
}

.avatar {
  width: 11cqw;
  height: 11cqw;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f8ff7, #c74ff7);
  border: 0.4cqw solid #fff;
}

.avatar.sm {
  width: 7cqw;
  height: 7cqw;
  border-width: 0.28cqw;
}

.avatar.xs {
  width: 5.4cqw;
  height: 5.4cqw;
  border-width: 0.22cqw;
}

.avatar.ring {
  box-shadow: 0 0 0 0.5cqw #0f0f0f, 0 0 0 0.9cqw #f74f4f;
}

.follow-badge {
  position: absolute;
  bottom: -1.8cqw;
  left: 50%;
  transform: translateX(-50%);
  width: 4.4cqw;
  height: 4.4cqw;
  border-radius: 50%;
  background: #fe2c55;
  color: #fff;
  font-size: 3.2cqw;
  font-weight: 700;
  line-height: 4.1cqw;
  text-align: center;
  text-shadow: none;
}

.disc {
  width: 9.4cqw;
  height: 9.4cqw;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, #555 0 22%, #111 22% 100%);
  border: 0.3cqw solid #2a2a2a;
}

.audio-thumb {
  width: 8cqw;
  height: 8cqw;
  border-radius: 1.4cqw;
  background: linear-gradient(135deg, #f7c94f, #f74f4f);
  border: 0.4cqw solid rgba(255, 255, 255, 0.85);
}

.dots {
  height: 5cqw;
}

/* ---------- bottom caption block ---------- */
.caption-block {
  position: absolute;
  left: 4.1cqw;
  right: 18cqw;
  display: flex;
  flex-direction: column;
  gap: 1.4cqw;
}

.tiktok .caption-block {
  bottom: 11.5cqw;
}

.ig-reels .caption-block {
  bottom: 12.5cqw;
}

.handle {
  font-size: 3.6cqw;
  font-weight: 700;
}

.caption {
  font-size: 3.2cqw;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.music {
  display: flex;
  align-items: center;
  gap: 1.4cqw;
  font-size: 2.9cqw;
}

.note {
  width: 3.4cqw;
  height: 3.4cqw;
  flex-shrink: 0;
}

.ig-user-row {
  display: flex;
  align-items: center;
  gap: 1.8cqw;
}

.follow-pill {
  font-size: 2.7cqw;
  font-weight: 600;
  padding: 0.7cqw 2.4cqw;
  border: 0.28cqw solid rgba(255, 255, 255, 0.85);
  border-radius: 1.2cqw;
  text-shadow: none;
}

/* ---------- bottom nav ---------- */
.nav {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 8.6cqw;
  display: flex;
  align-items: center;
  justify-content: space-around;
  background: #000;
  font-size: 2.5cqw;
  border-radius: 0 0 8px 8px;
}

.nav-item {
  opacity: 0.55;
}

.nav-item.active {
  opacity: 1;
  font-weight: 600;
}

.create {
  width: 9.6cqw;
  height: 6cqw;
  border-radius: 1.4cqw;
  background: #fff;
  color: #000;
  font-size: 4cqw;
  font-weight: 700;
  line-height: 5.6cqw;
  text-align: center;
  text-shadow: none;
}

/* ---------- Instagram feed (chrome sits outside the media) ---------- */
.feed-header {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 1.4cqw;
  display: flex;
  align-items: center;
  gap: 2.4cqw;
  padding: 0 1cqw;
}

.feed-header-text {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.feed-header-text .handle {
  font-size: 3.2cqw;
}

.sub {
  font-size: 2.7cqw;
  color: var(--text-muted);
}

.dots-h {
  width: 4.4cqw;
  height: 4.4cqw;
}

.feed-footer {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 2cqw;
  display: flex;
  flex-direction: column;
  gap: 1.6cqw;
  padding: 0 1cqw;
}

.feed-actions {
  display: flex;
  align-items: center;
  gap: 3.4cqw;
}

.feed-actions .ic {
  width: 5.6cqw;
  height: 5.6cqw;
}

.feed-actions .save {
  margin-left: auto;
}

.feed-likes {
  font-size: 3.1cqw;
  font-weight: 700;
}

.feed-caption {
  font-size: 3.1cqw;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.feed-caption .handle {
  font-size: 3.1cqw;
  margin-right: 0.8cqw;
}

/* ---------- safe zone guides ---------- */
.safe-layer {
  position: absolute;
  inset: 0;
  overflow: hidden;
  border-radius: 8px;
}

.safe {
  position: absolute;
  border: 0.3cqw dashed rgba(255, 96, 96, 0.9);
  border-radius: 1cqw;
  /* The oversized spread tints everything outside the safe rect. */
  box-shadow: 0 0 0 200cqw rgba(220, 40, 40, 0.16);
}

.safe-label {
  position: absolute;
  top: 0.8cqw;
  left: 0.8cqw;
  font-size: 2.4cqw;
  font-weight: 600;
  color: rgba(255, 140, 140, 0.95);
  text-shadow: none;
}
</style>
