import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { vnextClient } from "./vnext-client";
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

export const vnextKeys = {
  all: ["vnext"] as const,
  captures: () => [...vnextKeys.all, "captures"] as const,
  captureSession: (id: string) =>
    [...vnextKeys.all, "capture-session", id] as const,
  reviews: () => [...vnextKeys.all, "reviews"] as const,
  review: (id: string) => [...vnextKeys.all, "review", id] as const,
  candidates: () => [...vnextKeys.all, "candidates"] as const,
  results: (captureId: string) =>
    [...vnextKeys.all, "results", captureId] as const
};

// -- Capture hooks --

export function useCreateCaptureSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CaptureSessionCreateRequest) =>
      vnextClient.createCaptureSession(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: vnextKeys.captures() });
    }
  });
}

export function useListCaptures() {
  return useQuery<CaptureItemResponse[]>({
    queryKey: vnextKeys.captures(),
    queryFn: () => vnextClient.listCaptures()
  });
}

export function useCaptureSession(sessionId: string | null) {
  return useQuery<CaptureSessionDetailResponse>({
    queryKey: sessionId
      ? vnextKeys.captureSession(sessionId)
      : vnextKeys.captureSession(""),
    queryFn: () => {
      if (!sessionId) throw new Error("Session ID required");
      return vnextClient.getCaptureSession(sessionId);
    },
    enabled: Boolean(sessionId)
  });
}

export function useApplyCaptureDecision() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      captureId,
      payload
    }: {
      captureId: string;
      payload: CaptureDecisionRequest;
    }) => vnextClient.applyCaptureDecision(captureId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: vnextKeys.captures() });
    }
  });
}

// -- Weekly Review hooks --

export function useStartWeeklyReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => vnextClient.startWeeklyReview(),
    onSuccess: (data) => {
      queryClient.setQueryData(vnextKeys.review(data.review.id), data);
      queryClient.invalidateQueries({ queryKey: vnextKeys.reviews() });
    }
  });
}

export function useWeeklyReview(reviewId: string | null) {
  return useQuery<WeeklyReviewDetailResponse>({
    queryKey: reviewId ? vnextKeys.review(reviewId) : vnextKeys.review(""),
    queryFn: () => {
      if (!reviewId) throw new Error("Review ID required");
      return vnextClient.getWeeklyReview(reviewId);
    },
    enabled: Boolean(reviewId)
  });
}

export function useListWeeklyReviews() {
  return useQuery<WeeklyReviewResponse[]>({
    queryKey: vnextKeys.reviews(),
    queryFn: () => vnextClient.listWeeklyReviews()
  });
}

export function useRecordReviewOutcome() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      reviewId,
      captureId,
      payload
    }: {
      reviewId: string;
      captureId: string;
      payload: ReviewOutcomeRequest;
    }) =>
      vnextClient.recordReviewOutcome(reviewId, captureId, payload),
    onSuccess: (_data, { reviewId }) => {
      queryClient.invalidateQueries({
        queryKey: vnextKeys.review(reviewId)
      });
    }
  });
}

export function useCompleteWeeklyReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reviewId: string) =>
      vnextClient.completeWeeklyReview(reviewId),
    onSuccess: (_data, reviewId) => {
      queryClient.invalidateQueries({
        queryKey: vnextKeys.review(reviewId)
      });
      queryClient.invalidateQueries({
        queryKey: vnextKeys.reviews()
      });
      queryClient.invalidateQueries({
        queryKey: vnextKeys.captures()
      });
    }
  });
}

// -- Candidate hooks --

export function useListCandidates() {
  return useQuery<ProblemCandidateResponse[]>({
    queryKey: vnextKeys.candidates(),
    queryFn: () => vnextClient.listCandidates()
  });
}

export function useCreateCandidate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CandidateCreateRequest) =>
      vnextClient.createCandidate(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: vnextKeys.candidates()
      });
    }
  });
}

export function useRequestPromotion() {
  const queryClient = useQueryClient();
  return useMutation<
    CrtPromotionResponse,
    unknown,
    string
  >({
    mutationFn: (candidateId: string) =>
      vnextClient.requestPromotion(candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: vnextKeys.candidates()
      });
    }
  });
}

// -- Evidence/Result hooks --

export function useCaptureResults(captureId: string | null) {
  return useQuery<EvidenceResultResponse[]>({
    queryKey: captureId
      ? vnextKeys.results(captureId)
      : vnextKeys.results(""),
    queryFn: () => {
      if (!captureId) throw new Error("Capture ID required");
      return vnextClient.getCaptureResults(captureId);
    },
    enabled: Boolean(captureId)
  });
}

export function useRecordResult() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: EvidenceResultCreateRequest) =>
      vnextClient.recordResult(payload),
    onSuccess: (_data, variables) => {
      if (variables.atomic_capture_ids.length > 0) {
        queryClient.invalidateQueries({
          queryKey: vnextKeys.results(variables.atomic_capture_ids[0])
        });
      }
    }
  });
}
