package main

import (
	"database/sql"
	"log"
	"net/http"
	"time"
)

func main() {
	db, err := sql.Open("sqlite", "widgets.db")
	if err != nil {
		log.Fatal(err)
	}
	server := &Server{store: &Store{db: db}}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /widgets/{id}", server.getWidget)
	mux.HandleFunc("POST /widgets", server.createWidget)
	mux.HandleFunc("PUT /widgets/{id}", server.renameWidget)
	httpServer := &http.Server{
		Addr:         ":8080",
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
	}
	log.Fatal(httpServer.ListenAndServe())
}
