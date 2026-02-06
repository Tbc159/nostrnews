package store

import (
	"database/sql"

	_ "github.com/mattn/go-sqlite3"
)

type Store struct {
	db *sql.DB
}

func New(path string) (*Store, error) {
	db, err := sql.Open("sqlite3", path)
	if err != nil {
		return nil, err
	}

	_, err = db.Exec(`
	    CREATE TABLE IF NOT EXISTS published (
	        id INTEGER PRIMARY KEY AUTOINCREMENT, -- Nuova colonna ID
	        guid TEXT UNIQUE,                     -- GUID resta per evitare duplicati RSS
	        published_at INTEGER NOT NULL,
	        title TEXT,
	        link TEXT,
	        author TEXT,
	        content TEXT,
	        category TEXT,
	        tags TEXT,
	        status TEXT DEFAULT 'draft',
	        tg_sent INTEGER DEFAULT 0
	    )
	`)
	if err != nil {
		db.Close()
		return nil, err
	}

	_, err = db.Exec(`CREATE INDEX IF NOT EXISTS idx_published_at ON published(published_at)`)
	if err != nil {
		db.Close()
		return nil, err
	}

	return &Store{db: db}, nil
}

func (s *Store) IsPublished(guid string) bool {
	var count int
	err := s.db.QueryRow("SELECT COUNT(*) FROM published WHERE guid = ?", guid).Scan(&count)
	if err != nil {
		return false
	}
	return count > 0
}

func (s *Store) MarkPublished(guid string, ts int64, title string, link string, author string, content string, cat string, tags string, status string) error {
    _, err := s.db.Exec(
        "INSERT OR REPLACE INTO published (guid, published_at, title, link, author, content, category, tags, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        guid, ts, title, link, author, content, cat, tags, status,
    )
    return err
}

func (s *Store) GetStatus(guid string) (status string, exists bool) {
	err := s.db.QueryRow("SELECT status FROM published WHERE guid = ?", guid).Scan(&status)
	if err != nil {
		return "", false
	}
	return status, true
}

func (s *Store) Close() error {
	return s.db.Close()
}

func (s *Store) Cleanup(olderThan int64) (int64, error) {
	result, err := s.db.Exec("DELETE FROM published WHERE published_at < ?", olderThan)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}
