// ==UserScript==
// @name         YouTube MP3 Auto-Downloader
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Automatically sends YouTube videos to local MP3 downloader
// @author       You
// @match        https://www.youtube.com/*
// @icon         https://www.youtube.com/favicon.ico
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function() {
    'use strict';

    const BACKEND_URL = 'http://127.0.0.1:8000/seen';
    let lastVideoId = null;
    let lastTitle = null;
    let lastChannel = null;

    /**
     * Extract video ID from current URL
     */
    function getVideoIdFromUrl() {
        const params = new URLSearchParams(window.location.search);
        return params.get('v');
    }

    /**
     * Get video title from page metadata or DOM
     */
    function getVideoTitle() {
        // Try the primary video title element (most reliable for YouTube)
        let title = document.querySelector('#title h1.ytd-watch-metadata yt-formatted-string')?.textContent;
        if (title && title.trim()) return title.trim();
        
        // Try alternative watch page title
        title = document.querySelector('h1.title yt-formatted-string')?.textContent;
        if (title && title.trim()) return title.trim();
        
        // Try meta property (may be stale on SPA navigation)
        title = document.querySelector('meta[property="og:title"]')?.content;
        if (title && title.trim()) return title.trim();

        // Try meta tag
        title = document.querySelector('meta[name="title"]')?.content;
        if (title && title.trim()) return title.trim();

        // Fallback to page title
        title = document.title.split(' - ')[0].trim();
        return title || 'Unknown';
    }

    /**
     * Get channel name from page
     */
    function getChannelName() {
        // Try the primary channel name element
        let channel = document.querySelector('ytd-channel-name#channel-name yt-formatted-string a')?.textContent;
        if (channel && channel.trim()) return channel.trim();
        
        // Try alternative channel link
        channel = document.querySelector('ytd-video-owner-renderer a.yt-simple-endpoint')?.textContent;
        if (channel && channel.trim()) return channel.trim();
        
        // Try to find channel link in header
        const channelLink = document.querySelector('ytd-channel-tagline-renderer a#channel-name a');
        if (channelLink) {
            return channelLink.textContent.trim();
        }

        // Alternative: look for channel name in metadata
        const channelEl = document.querySelector('a.yt-simple-endpoint[href*="/channel/"], a.yt-simple-endpoint[href*="/@"]');
        if (channelEl) {
            return channelEl.textContent.trim();
        }

        // Fallback to page title if it contains channel name
        const pageTitle = document.title;
        if (pageTitle.includes('-')) {
            return pageTitle.split('-').pop().trim();
        }

        return 'Unknown Channel';
    }

    /**
     * Send video info to backend
     */
    function sendVideoToBackend(videoId, title, channel) {
        const payload = {
            videoId: videoId,
            title: title,
            channel: channel
        };

        console.log('[YT-MP3] Sending:', payload);

        GM_xmlhttpRequest({
            method: 'POST',
            url: BACKEND_URL,
            headers: {
                'Content-Type': 'application/json'
            },
            data: JSON.stringify(payload),
            onload: function(response) {
                try {
                    const result = JSON.parse(response.responseText);
                    console.log('[YT-MP3] Response:', result);
                } catch (e) {
                    console.log('[YT-MP3] Response received (non-JSON)');
                }
            },
            onerror: function(error) {
                console.error('[YT-MP3] Error:', error);
            }
        });
    }

    /**
     * Check if video has changed and notify backend
     */
    function checkAndNotify() {
        const videoId = getVideoIdFromUrl();

        // Not a watch page or no video ID
        if (!videoId) {
            lastVideoId = null;
            return;
        }

        // Same video, ignore
        if (videoId === lastVideoId) {
            return;
        }

        // New video detected
        lastVideoId = videoId;
        lastTitle = getVideoTitle();
        lastChannel = getChannelName();

        console.log('[YT-MP3] New video detected:', videoId);
        
        // Small delay to ensure page metadata is loaded
        setTimeout(() => {
            lastTitle = getVideoTitle();
            lastChannel = getChannelName();
            sendVideoToBackend(videoId, lastTitle, lastChannel);
        }, 500);
    }

    /**
     * Set up observers for YouTube SPA navigation
     */
    function setupObservers() {
        // Listen for URL changes
        let lastUrl = window.location.href;
        const urlObserver = setInterval(() => {
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;
                console.log('[YT-MP3] URL changed:', lastUrl);
                checkAndNotify();
            }
        }, 500);

        // Also watch for DOM changes in case video player changes without URL change
        const pageChangeObserver = new MutationObserver(() => {
            checkAndNotify();
        });

        // Observe header and main content area
        const mainContent = document.querySelector('ytd-page-manager') || document.body;
        pageChangeObserver.observe(mainContent, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['href']
        });

        // Initial check
        setTimeout(checkAndNotify, 1000);

        console.log('[YT-MP3] Script initialized');
    }

    /**
     * Wait for page to be ready and initialize
     */
    function init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setupObservers);
        } else {
            setupObservers();
        }
    }

    init();
})();
