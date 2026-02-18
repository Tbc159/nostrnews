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
	"wss://nostr-pub.wellorder.net",
	"wss://nostr-03.dorafactory.org",
	"wss://vitor.nostr1.com",
	"wss://relay.noswhere.com",
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
	// Subtract 1 Hour buffer to catch articles with slightly older timestamps
	startTime := time.Now().UTC().Add(-24 * time.Hour)
	log.Printf("Processing articles published after %s", startTime.Format(time.RFC3339))

	// Run continuously
	for {
		select {
		case <-ctx.Done():
			return
		default:
			processFeeds(ctx, cfg, fetcher, publisher, publishedStore, startTime)
			log.Println("Cycle completed. Waiting 60 seconds...")
			time.Sleep(60 * time.Second)
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
			log.Printf("Error fetching feed %s: %v", feed.URL, err)
			continue
		}

		for _, article := range articles {
			// 1. Check Link
			if article.Link == "" && strings.HasPrefix(article.GUID, "http") {
				article.Link = article.GUID
			}
			if article.Link == "" {
				log.Printf("⚠️ Article without a valid link: %s", article.Title)
				continue
			}

			// 2. Check if exsist
			currentStatus, exists := store.GetStatus(article.GUID)

			// If exist ignore
			if exists && (currentStatus == "published" || strings.HasPrefix(currentStatus, "skipped")) {
				continue
			}

			tagString := strings.Join(article.Tags, ",")
			if exists && currentStatus == "reviewed" {
			    log.Printf("💎 Article approved found: %s", article.Title)
			    dbArticle, err := store.GetArticle(article.GUID) 
			    if err == nil && dbArticle.Tags != "" {
			        article.Tags = strings.Split(dbArticle.Tags, ",")
			        log.Printf("[DEBUG] Using tags from DB: %v", article.Tags)
			    }
						    if err := publisher.Publish(ctx, article); err == nil {
			        err = store.UpdateStatus(article.GUID, "published")
			        if err != nil {
			            log.Printf("Error updating status to published: %v", err)
			        }
			        log.Printf("🚀 Published on Nostr: %s", article.Title)
			        time.Sleep(5 * time.Second)
			    } else {
			        log.Printf("❌ Nostr publication error: %v", err)
			    }
			    continue
			}

			// 4. Se l'articolo esiste già ma è ancora 'draft', non fare nulla (evita reinserimenti e log inutili)
			if exists && currentStatus == "draft" {
				continue
			}

			// 5. Gestione Nuovi Articoli (Inserimento solo se !exists)
			// Skip articles older than cutoff time (compare in UTC)
			if article.Published.UTC().Before(cutoff) {
				continue
			}

			// Prepare DB Content
			dbContent := article.Content
			if dbContent == "" {
				dbContent = article.Description
			}

			// Filtri di qualità per scartare subito
			newStatus := "draft"
			if article.Title == "" || article.Title == "Untitled" {
				newStatus = "skipped_no_title"
			} else if article.Description == "" && article.Content == "" {
				newStatus = "skipped_no_content"
			}

			// Salvataggio (Solo se nuovo)
			if !exists {
				err := store.MarkPublished(
					article.GUID,
					time.Now().Unix(),
					article.Title,
					article.Link,
					article.Author,
					dbContent,
					article.Category,
					tagString,
					newStatus,
				)
				if err != nil {
					log.Printf("DB Save error for %s: %v", article.GUID, err)
				} else if newStatus == "draft" {
					log.Printf("📥 New draft saved: %s", article.Title)
				}
			}
		}
	}
}