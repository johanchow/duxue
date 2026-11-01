package main

import (
	"context"
	"github.com/johanchow/duxue/duxue-gateway/internal/bootstrap"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	os.Exit(bootstrap.Execute(ctx, os.Args[1:], os.Stdout, os.Stderr))
}
