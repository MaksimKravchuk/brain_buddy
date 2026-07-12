// vNext API client methods — ADR-0001 endpoints

import { request } from "./client";
import type {
  CaptureDecisionRequest,
  CaptureItemResponse,
  CaptureSessionCreateRequest,
  CaptureSessionDetailResponse,
  CandidateCreateRequest,
  CrtPromotionResponse,
  EvidenceResultCreateRequest,
  EvidenceResultResponse,
  ProblemCandidateResponse,
  ReviewOutcomeRequest,
  ReviewOutcomeResponse,
  ReviewSummaryResponse,
  WeeklyReviewDetailResponse,
  WeeklyReviewResponse
} from "./vnext-types";

export const vnextClient = {
  // -- Capture --

  createCaptureSession(payload: CaptureSessionCreateRequest) {
    return request<CaptureSessionDetailResponse>("/capture-sessions", {
      method: "POST",
      body: payload
    });
  },

  getCaptureSession(sessionId: string) {
    return request<CaptureSessionDetailResponse>(`/capture-sessions/${sessionId}`);
  },

  listCaptures() {
    return request<CaptureItemResponse[]>("/captures");
  },

  applyCaptureDecision(captureId: string, payload: CaptureDecisionRequest) {
    return request<CaptureItemResponse>(`/captures/${captureId}/decisions`, {
      method: "POST",
      body: payload
    });
  },

  getCaptureResults(captureId: string) {
    return request<EvidenceResultResponse[]>(`/captures/${captureId}/results`);
  },

  // -- Weekly Review --

  startWeeklyReview() {
    return request<WeeklyReviewDetailResponse>("/weekly-reviews", {
      method: "POST"
    });
  },

  getWeeklyReview(reviewId: string) {
    return request<WeeklyReviewDetailResponse>(`/weekly-reviews/${reviewId}`);
  },

  listWeeklyReviews() {
    return request<WeeklyReviewResponse[]>("/weekly-reviews");
  },

  recordReviewOutcome(
    reviewId: string,
    captureId: string,
    payload: ReviewOutcomeRequest
  ) {
    return request<ReviewOutcomeResponse>(
      `/weekly-reviews/${reviewId}/items/${captureId}/outcomes`,
      { method: "POST", body: payload }
    );
  },

  completeWeeklyReview(reviewId: string) {
    return request<ReviewSummaryResponse>(`/weekly-reviews/${reviewId}/complete`, {
      method: "POST"
    });
  },

  // -- Problem Candidates --

  createCandidate(payload: CandidateCreateRequest) {
    return request<ProblemCandidateResponse>("/problem-candidates", {
      method: "POST",
      body: payload
    });
  },

  listCandidates() {
    return request<ProblemCandidateResponse[]>("/problem-candidates");
  },

  requestPromotion(candidateId: string) {
    return request<CrtPromotionResponse>(
      `/problem-candidates/${candidateId}/promotions`,
      { method: "POST" }
    );
  },

  // -- Evidence/Results --

  recordResult(payload: EvidenceResultCreateRequest) {
    return request<EvidenceResultResponse>("/results", {
      method: "POST",
      body: payload
    });
  }
};
