import { Alert, Container, Loader } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { fetchReview } from "./api";
import { messages } from "./messages";
import { Review } from "./Review";

export default function App() {
  const review = useQuery({ queryFn: fetchReview, queryKey: ["review"] });
  return (
    <Container size="md" py="xl">
      {review.isPending && <Loader />}
      {review.isError && (
        <Alert color="red" title={messages.loadFailed}>
          {String(review.error)}
        </Alert>
      )}
      {review.data && <Review review={review.data} />}
    </Container>
  );
}
