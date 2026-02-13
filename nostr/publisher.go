package nostr

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"
	"time"

	"nostrnews/rss"

	"github.com/nbd-wtf/go-nostr"
)

type Publisher struct {
	secretKey     string
	pubKey        string
	relays        []string
	pool          *nostr.SimplePool
	relayCooldown map[string]time.Time
	cooldownMu    sync.RWMutex
}

const rateLimitCooldown = 60 * time.Second

func NewPublisher(privateKeyHex string, relays []string) (*Publisher, error) {
	pubKey, err := nostr.GetPublicKey(privateKeyHex)
	if err != nil {
		return nil, fmt.Errorf("invalid private key: %w", err)
	}
	log.Printf("[Nostr] Starting publication with Key: %s", privateKeyHex)
	return &Publisher{
		secretKey:     privateKeyHex,
		pubKey:        pubKey,
		relays:        relays,
		pool:          nostr.NewSimplePool(context.Background()),
		relayCooldown: make(map[string]time.Time),
	}, nil
}

func (p *Publisher) Publish(ctx context.Context, article rss.Article) error {
	log.Printf("[Nostr DEBUG] Starting publication process for: %s", article.Title)

	archiveURL := GetArchiveURL(article.Link)
	content := p.buildContent(article, archiveURL)
	dTag := p.hashGUID(article.GUID)
	log.Printf("[Nostr DEBUG] Generated d-tag: %s from GUID: %s", dTag, article.GUID)

	tags := nostr.Tags{
		{"d", dTag},
		{"title", article.Title},
		{"published_at", strconv.FormatInt(article.Published.Unix(), 10)},
		{"r", article.Link},
	}

	if article.Description != "" {
		summary := article.Description
		if len(summary) > 500 {
			summary = summary[:497] + "..."
		}
		tags = append(tags, nostr.Tag{"summary", summary})
	}
	
	if article.ImageURL != "" { tags = append(tags, nostr.Tag{"image", article.ImageURL}) }
	
	if article.Country != "" { tags = append(tags, nostr.Tag{"country", article.Country}) }
	
	if article.Language != "" { tags = append(tags, nostr.Tag{"language", article.Language}) }
	
	if article.Category != "" { tags = append(tags, nostr.Tag{"category", article.Category}) }
	
	if article.Paywall != "" { tags = append(tags, nostr.Tag{"paywall", article.Paywall}) }
	
	tags = append(tags, nostr.Tag{"source", article.FeedName})
	
	if article.Author != "" { tags = append(tags, nostr.Tag{"author", article.Author}) }
	
	for _, t := range article.Tags { tags = append(tags, nostr.Tag{"t", t}) }
	
	tags = append(tags, nostr.Tag{"archive", archiveURL})

	log.Printf("[Nostr DEBUG] Total tags constructed: %d", len(tags))

	ev := nostr.Event{
		PubKey:    p.pubKey,
		CreatedAt: nostr.Now(),
		Kind:      30023,
		Tags:      tags,
		Content:   content,
	}

	if err := ev.Sign(p.secretKey); err != nil {
		log.Printf("[Nostr ERROR] Signing failed: %v", err)
		return fmt.Errorf("failed to sign event: %w", err)
	}
	log.Printf("[Nostr DEBUG] Event Signed Successfully. ID: %s", ev.ID)
	log.Printf("[Nostr DEBUG] RAW EVENT JSON: %s", ev.String())

	successCount := 0
	totalRelays := len(p.relays)
	for _, relayURL := range p.relays {
		log.Printf("[Nostr DEBUG] Attempting relay: %s", relayURL)
		if p.isInCooldown(relayURL) {
			log.Printf("[Nostr DEBUG] Relay %s skipped: currently in cooldown", relayURL)
			continue
		}

		relay, err := p.pool.EnsureRelay(relayURL)
		if err != nil {
			log.Printf("[Nostr ERROR] Connection failed for %s: %v", relayURL, err)
			continue
		}

		pubCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		err = relay.Publish(pubCtx, ev)
		cancel()

		if err != nil {
			errMsg := err.Error()
			log.Printf("[Nostr DEBUG] Relay %s returned error: %s", relayURL, errMsg)

			if strings.Contains(errMsg, "rate-limited") || strings.Contains(errMsg, "rate limit") {
				log.Printf("[Nostr WARNING] Rate limit hit on %s", relayURL)
				p.setCooldown(relayURL)
				continue
			}

			if strings.Contains(errMsg, "replaced") {
				log.Printf("[Nostr INFO] Event 30023 replaced on %s", relayURL)
				successCount++
				continue
			}

			log.Printf("[Nostr ERROR] Failed to publish to %s: %v", relayURL, err)
			continue
		}
		
		log.Printf("[Nostr SUCCESS] Accepted by %s", relayURL)
		successCount++
	}

	if successCount == 0 {
		log.Printf("[Nostr CRITICAL] Publication FAILED for '%s'. 0/%d relays accepted it.", article.Title, totalRelays)
		return fmt.Errorf("failed to publish to any relay")
	}

	log.Printf("[Nostr] Final status: %d/%d relays successful", successCount, totalRelays)
	return nil
}

func (p *Publisher) isInCooldown(relayURL string) bool {
	p.cooldownMu.RLock()
	defer p.cooldownMu.RUnlock()
	cooldownUntil, exists := p.relayCooldown[relayURL]
	if !exists {
		return false
	}
	return time.Now().Before(cooldownUntil)
}

func (p *Publisher) setCooldown(relayURL string) {
	p.cooldownMu.Lock()
	defer p.cooldownMu.Unlock()
	p.relayCooldown[relayURL] = time.Now().Add(rateLimitCooldown)
}

func (p *Publisher) buildContent(article rss.Article, archiveURL string) string {
	var sb strings.Builder

	sb.WriteString(fmt.Sprintf("**Source:** [%s](%s) | [archive](%s)\n\n---\n\n", article.FeedName, article.Link, archiveURL))

	body := article.Content
	if body == "" {
		body = article.Description
	}

	sb.WriteString(body)

	return sb.String()
}

func (p *Publisher) hashGUID(guid string) string {
	h := sha256.Sum256([]byte(guid))
	return hex.EncodeToString(h[:16])
}

func (p *Publisher) Close() {

}

func GetArchiveURL(articleURL string) string {
	return "https://archive.is/newest/" + articleURL
}
