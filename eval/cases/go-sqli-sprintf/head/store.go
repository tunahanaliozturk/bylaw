package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
)

type Widget struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

var ErrNotFound = errors.New("not found")

type Store struct {
	db *sql.DB
}

func (s *Store) Widget(ctx context.Context, id int64) (Widget, error) {
	var w Widget
	err := s.db.QueryRowContext(ctx, "SELECT id, name FROM widgets WHERE id = ?", id).Scan(&w.ID, &w.Name)
	if errors.Is(err, sql.ErrNoRows) {
		return Widget{}, ErrNotFound
	}
	if err != nil {
		return Widget{}, fmt.Errorf("load widget %d: %w", id, err)
	}
	return w, nil
}

func (s *Store) Create(ctx context.Context, name string) (Widget, error) {
	result, err := s.db.ExecContext(ctx, "INSERT INTO widgets (name) VALUES (?)", name)
	if err != nil {
		return Widget{}, fmt.Errorf("insert widget: %w", err)
	}
	id, err := result.LastInsertId()
	if err != nil {
		return Widget{}, fmt.Errorf("read widget id: %w", err)
	}
	return Widget{ID: id, Name: name}, nil
}

func (s *Store) FindByName(ctx context.Context, name string) ([]Widget, error) {
	query := fmt.Sprintf("SELECT id, name FROM widgets WHERE name = '%s'", name)
	rows, err := s.db.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("find widgets: %w", err)
	}
	defer rows.Close()
	var found []Widget
	for rows.Next() {
		var w Widget
		if err := rows.Scan(&w.ID, &w.Name); err != nil {
			return nil, fmt.Errorf("scan widget: %w", err)
		}
		found = append(found, w)
	}
	return found, rows.Err()
}
