package main

import (
	"net/http/httptest"
	"testing"
)

func TestWriteJSONSetsTheContentType(t *testing.T) {
	recorder := httptest.NewRecorder()
	writeJSON(recorder, 201, map[string]string{"name": "a"})
	if got := recorder.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("content type %q", got)
	}
	if recorder.Code != 201 {
		t.Fatalf("status %d", recorder.Code)
	}
}
