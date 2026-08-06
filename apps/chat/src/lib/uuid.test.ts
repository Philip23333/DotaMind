import { describe, expect, it, vi } from "vitest";

import { createUuidV4 } from "./uuid";

describe("createUuidV4", () => {
  it("uses the platform randomUUID implementation when available", () => {
    const randomUUID = vi.fn(() => "11111111-2222-4333-8444-555555555555");
    const getRandomValues = vi.fn(() => {
      throw new Error("getRandomValues should not run");
    });

    expect(createUuidV4({ randomUUID, getRandomValues })).toBe(
      "11111111-2222-4333-8444-555555555555",
    );
    expect(randomUUID).toHaveBeenCalledOnce();
    expect(getRandomValues).not.toHaveBeenCalled();
  });

  it("creates an RFC 4122 version 4 UUID when randomUUID is unavailable", () => {
    const getRandomValues = vi.fn((array: Uint8Array) => {
      array.set(Array.from({ length: 16 }, (_, index) => index));
      return array;
    });

    expect(createUuidV4({ getRandomValues })).toBe(
      "00010203-0405-4607-8809-0a0b0c0d0e0f",
    );
    expect(getRandomValues).toHaveBeenCalledOnce();
  });
});
