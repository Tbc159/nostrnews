package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"
	"strings"

	"nostrnews/config"
	"nostrnews/nostr"
	"nostrnews/rss"
	"nostrnews/store"
)

const (
	storePath = "published.db"
)

var defaultRelays = []string{
	"wss://relay.damus.io",
	"wss://nos.lol",
	"wss://relay.primal.net",
	"wss://relay.snort.social",
	"wss://nostr.land",
	"wss://nostr-pub.wellorder.net",
	"wss://offchain.pub",
	"wss://relay.nostr.band",
}


func main() {
	// Get private key from environment
	privateKey := os.Getenv("NOSTR_PRIVATE_KEY")
	if privateKey == "" {
		log.Fatal("NOSTR_PRIVATE_KEY environment variable is required")
	}

	// Load embedded feed configuration
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}
	log.Printf("Loaded %d feeds", len(cfg.Feeds))

	// Initialize store
	publishedStore, err := store.New(storePath)
	if err != nil {
		log.Fatalf("Failed to initialize store: %v", err)
	}
	defer publishedStore.Close()

	// Initialize components
	fetcher := rss.NewFetcher()
	publisher, err := nostr.NewPublisher(privateKey, defaultRelays)
	if err != nil {
		log.Fatalf("Failed to create publisher: %v", err)
	}
	defer publisher.Close()

	// Setup graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigChan
		log.Println("Shutting down...")
		cancel()
	}()

	// Only process articles published after program start (use UTC for consistent comparison)
	// Subtract 5 minutes buffer to catch articles with slightly older timestamps
		//startTime := time.Now().UTC().Add(-5 * time.Minute)
	//log.Printf("Will only process articles published after %s", startTime.Format(time.RFC3339))
	// Modified dubtract in 2 hours from 5 minutes buffer, to test catching articles with slightly older timestamps
	startTime := time.Now().UTC().Add(-10 * time.Hour)
	log.Printf("Will only process articles published after %s", startTime.Format(time.RFC3339))

	// Run continuously
	for {
		select {
		case <-ctx.Done():
			return
		default:
			processFeeds(ctx, cfg, fetcher, publisher, publishedStore, startTime)
		}
	}
}

func processFeeds(ctx context.Context, cfg *config.Config, fetcher *rss.Fetcher, publisher *nostr.Publisher, store *store.Store, cutoff time.Time) {
	for _, feed := range cfg.Feeds {
		select {
		case <-ctx.Done():
			return
		default:
		}

		articles, err := fetcher.Fetch(ctx, feed)
		if err != nil {
			// Silently skip fetch errors
			continue
		}

		for _, article := range articles {
    // 1. Recover previous statment
			currentStatus, exists := store.GetStatus(article.GUID)

			// Skip if already published
			if exists && currentStatus == "published" {
				continue
			}

			// Skip untitled articles
			if article.Title == "" || article.Title == "Untitled" {
				store.MarkPublished(article.GUID, time.Now().Unix(), article.Category, strings.Join(article.Tags, ","), "skipped_no_title")
				continue
			}

			// Skip articles without cover image
			/*if article.ImageURL == "" {
			    log.Printf("DEBUG: Skipping article (no cover image): %s", article.Title)
				store.MarkPublished(article.GUID, time.Now().Unix())
				continue
			}*/

			// Skip articles without description
			if article.Description == "" && article.Content == "" {
				store.MarkPublished(article.GUID, time.Now().Unix(), article.Category, strings.Join(article.Tags, ","), "skipped_no_content")
				continue
			}

			// Skip articles older than cutoff time (compare in UTC)
			if article.Published.UTC().Before(cutoff) {
				continue
			}

			// Transform tags in string for DB
			tagString := strings.Join(article.Tags, ",")

			// check if ready for publish
			shouldPublish := false
			newStatus := "draft"

			// Auto Publish if article is reviewed
			if exists && currentStatus == "reviewed" {
				shouldPublish = true
			}

			// Auto Publish if article was tag with "Bitcoin"
    		isBitcoin := false
			for _, t := range article.Tags {
				if strings.EqualFold(t, "Bitcoin") {
					isBitcoin = true
					break
				}
			}
			if isBitcoin {
				shouldPublish = true
			}

			// Execution
			if shouldPublish {
				if err := publisher.Publish(ctx, article); err == nil {
					newStatus = "published"
					log.Printf("🚀 Pubblicato: %s", article.Title)
				} else {
					log.Printf("❌ Errore pubblicazione: %v", err)
					newStatus = currentStatus
				}
			}

			// Update or save in DB
			store.MarkPublished(article.GUID, time.Now().Unix(), article.Category, tagString, newStatus)

			if shouldPublish {
				time.Sleep(60 * time.Second)
			}
		}
	}
}