package main

/*
Befor starting script in run
go get github.com/nbd-wtf/go-nostr/nip19@v0.42.1
export NOSTR_PRIVATE_KEY_NSEC="nsec123abc..."
*/

import (
        "fmt"
        "os"
        "strings"

        "github.com/nbd-wtf/go-nostr/nip19"
)

func main() {
        nsec := os.Getenv("NOSTR_PRIVATE_KEY_NSEC")

        // 2. Verifica se la variabile è vuota
        if nsec == "" {
                fmt.Fprintln(os.Stderr, "Errore: la variabile d'ambiente NOSTR_PRIVATE_KEY_NSEC non è impostata.")
                os.Exit(1)
        }

        // Pulizia di eventuali spazi o ritorni a capo
        nsec = strings.TrimSpace(nsec)

        // 3. Decodifica la chiave (da nsec a hex)
        prefix, hexKey, err := nip19.Decode(nsec)
        if err != nil {
                fmt.Fprintf(os.Stderr, "Errore nella decodifica: %v\n", err)
                os.Exit(1)
        }

        // 4. Verifica che sia effettivamente una chiave privata (nsec)
        if prefix != "nsec" {
                fmt.Fprintf(os.Stderr, "Errore: la chiave fornita non è un nsec (prefisso trovato: %s)\n", prefix)
                os.Exit(1)
        }

        // 5. Stampa a video solo il risultato in formato hex
        fmt.Printf("%x\n", hexKey)
}